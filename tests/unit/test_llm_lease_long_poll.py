"""POST /llm-jobs/lease with wait_seconds: held until a job is queued (synthetic, SQLite).

23-Nov-2026: a worker found a new job only at its next poll (every 10 s, longer
after a sign-in check). A lease that asks to wait is now held and answered the
moment a job is queued. A lease that does not ask is answered at once, as before.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api.routers import llm_jobs
from tce.db.session import get_db
from tce.llm import queue
from tce.llm.provider import LLMRequest
from tce.models.content_run import WorkerGroupState
from tce.models.llm_job import LLMJob
from tce.settings import settings
from tests.editorial_db import create_tables

KEY = "synthetic-test-key"
AUTH = {"Authorization": f"Bearer {KEY}"}
LEASE = "/api/v1/llm-jobs/lease"


def held() -> int:
    return getattr(queue, "held_lease_count", lambda: 0)()


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'lease.sqlite'}", poolclass=NullPool
    )
    await create_tables(engine)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    out = {"now": 0}

    def checkout(*_a):
        out["now"] += 1

    def checkin(*_a):
        out["now"] -= 1

    event.listen(engine.sync_engine, "checkout", checkout)
    event.listen(engine.sync_engine, "checkin", checkin)

    async def override_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(llm_jobs.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
        c.maker = maker  # type: ignore[attr-defined]
        c.app = app  # type: ignore[attr-defined]
        c.connections = out  # type: ignore[attr-defined]
        yield c
    await engine.dispose()
    assert held() == 0, "a held lease was left registered"


async def enqueue(client, text="synthetic", job_type="editorial_conversation"):
    async with client.maker() as s:
        job = await queue.enqueue(
            s,
            LLMRequest(
                job_type=job_type,
                agent_name="a",
                messages=[{"role": "user", "content": text}],
            ),
        )
        await s.commit()
        return job


async def held_count_reaches(n: int, within: float = 2.0) -> None:
    deadline = time.monotonic() + within
    while held() < n:
        assert time.monotonic() < deadline, f"expected {n} held leases"
        await asyncio.sleep(0.01)


async def test_a_plain_lease_answers_at_once_in_todays_shape(rig):
    t = time.monotonic()
    empty = await rig.post(LEASE, json={"worker_id": "old-worker"}, headers=AUTH)
    assert time.monotonic() - t < 0.5
    assert empty.status_code == 200 and empty.json() == {"job": None}

    job = await enqueue(rig)
    got = await rig.post(LEASE, json={"worker_id": "old-worker", "lease_seconds": 600}, headers=AUTH)
    body = got.json()
    assert list(body) == ["job"] and body["job"]["id"] == str(job.id)
    async with rig.maker() as s:
        row = await queue.get_job(s, job.id)
        expected = queue.job_to_dict(row, include_request=True, include_result=False)
    assert body["job"] == json.loads(json.dumps(expected, default=str))


async def test_a_waiting_lease_returns_within_a_fraction_of_a_second_of_an_enqueue(rig):
    asked = asyncio.create_task(
        rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 20}, headers=AUTH)
    )
    await asyncio.sleep(0.4)
    assert not asked.done(), "with nothing queued the request is held"
    job = await enqueue(rig)
    queued_at = time.monotonic()
    answer = await asyncio.wait_for(asked, timeout=5)
    took = time.monotonic() - queued_at
    assert answer.json()["job"]["id"] == str(job.id)
    assert took < 0.5, f"answered {took:.2f}s after the enqueue"


async def test_a_waiting_lease_takes_a_job_already_queued_at_once(rig):
    job = await enqueue(rig)
    t = time.monotonic()
    got = await rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 20}, headers=AUTH)
    assert got.json()["job"]["id"] == str(job.id) and time.monotonic() - t < 0.5


async def test_a_waiting_lease_ends_with_the_normal_empty_answer_at_its_bound(rig, monkeypatch):
    t = time.monotonic()
    got = await rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 1.0}, headers=AUTH)
    took = time.monotonic() - t
    assert got.status_code == 200 and got.json() == {"job": None}
    assert 0.9 <= took < 2.0, took

    # However long it asks for, the server holds it at most LEASE_WAIT_MAX_S.
    monkeypatch.setattr(llm_jobs, "LEASE_WAIT_MAX_S", 0.6, raising=False)
    t = time.monotonic()
    got = await rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 9999}, headers=AUTH)
    assert got.json() == {"job": None} and time.monotonic() - t < 1.5


@pytest.mark.parametrize("wait", [0, -5, None])
async def test_a_zero_or_negative_wait_is_a_plain_lease(rig, wait):
    t = time.monotonic()
    got = await rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": wait}, headers=AUTH)
    assert got.json() == {"job": None} and time.monotonic() - t < 0.5


async def test_a_waiting_lease_holds_no_database_connection_while_it_waits(rig):
    asked = asyncio.create_task(
        rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 3}, headers=AUTH)
    )
    await held_count_reaches(1)
    samples = []
    for _ in range(12):
        await asyncio.sleep(0.1)
        samples.append(rig.connections["now"])
    assert max(samples) == 0, f"connections checked out during the hold: {samples}"
    job = await enqueue(rig)
    assert (await asyncio.wait_for(asked, timeout=5)).json()["job"]["id"] == str(job.id)


async def test_a_job_written_by_another_process_is_found_by_looking_again(rig, monkeypatch):
    # No in-process wake at all: the row appears the way another process would write it.
    monkeypatch.setattr(queue, "wake_lease_waiters", lambda: 0, raising=False)
    asked = asyncio.create_task(
        rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 20}, headers=AUTH)
    )
    await asyncio.sleep(0.4)
    assert not asked.done(), "with nothing queued the request is held"
    async with rig.maker() as s:
        row = LLMJob(
            job_type="video_edit_request",
            agent_name="other-process",
            status="queued",
            idempotency_key="written-elsewhere",
            request_json={"messages": [{"role": "user", "content": "synthetic"}]},
            policy_model="claude-opus-5-5",
            input_hash="0" * 64,
            attempt_count=0,
            max_attempts=3,
        )
        s.add(row)
        await s.commit()
        row_id = row.id
    written_at = time.monotonic()
    answer = await asyncio.wait_for(asked, timeout=10)
    took = time.monotonic() - written_at
    assert answer.json()["job"]["id"] == str(row_id)
    assert took <= getattr(llm_jobs, "LEASE_LOOK_AGAIN_S", 0) + 0.5, f"found after {took:.2f}s"


async def test_held_leases_are_bounded_and_the_rest_answer_at_once(rig, monkeypatch):
    monkeypatch.setattr(llm_jobs, "MAX_HELD_LEASES", 2)
    holding = [
        asyncio.create_task(
            rig.post(LEASE, json={"worker_id": f"w{i}", "wait_seconds": 2}, headers=AUTH)
        )
        for i in range(2)
    ]
    await held_count_reaches(2)
    t = time.monotonic()
    third = await rig.post(LEASE, json={"worker_id": "w3", "wait_seconds": 2}, headers=AUTH)
    assert third.json() == {"job": None} and time.monotonic() - t < 0.5
    job = await enqueue(rig)
    answers = [r.json() for r in await asyncio.gather(*holding)]
    jobs = [a["job"]["id"] for a in answers if a["job"]]
    assert jobs == [str(job.id)], "exactly one held request takes the job"
    assert held() == 0


async def test_a_pause_set_by_another_session_is_obeyed_on_every_look(rig):
    asked = asyncio.create_task(
        rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 2.5}, headers=AUTH)
    )
    await held_count_reaches(1)
    async with rig.maker() as s:
        s.add(WorkerGroupState(group_key=queue.WORKER_GROUP_KEY, state="refused_policy"))
        await s.commit()
    job = await enqueue(rig)
    answer = await asyncio.wait_for(asked, timeout=5)
    assert answer.json() == {"job": None}
    async with rig.maker() as s:
        row = await queue.get_job(s, job.id)
        assert row.status == "queued" and row.attempt_count == 0


async def _drive(app, body: dict, disconnect_after: float | None, drop: asyncio.Event | None = None):
    """Call the ASGI app directly, so the client can go away mid-request."""
    sent: list[dict] = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        if drop is not None:
            await drop.wait()
        else:
            await asyncio.sleep(disconnect_after)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": LEASE,
        "raw_path": LEASE.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"authorization", f"Bearer {KEY}".encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    return sent


async def test_a_held_lease_is_released_at_once_when_its_client_goes_away(rig):
    t = time.monotonic()
    await asyncio.wait_for(
        _drive(rig.app, {"worker_id": "gone", "wait_seconds": 20}, disconnect_after=0.3),
        timeout=5,
    )
    took = time.monotonic() - t
    assert took < 0.8, f"released {took:.2f}s after it started (client left at 0.3s)"
    assert held() == 0
    job = await enqueue(rig)
    await asyncio.sleep(0.2)
    async with rig.maker() as s:
        row = await queue.get_job(s, job.id)
        assert row.status == "queued" and row.lease_owner is None


async def test_a_job_leased_as_its_client_goes_away_is_rolled_back(rig, monkeypatch):
    drop = asyncio.Event()
    real = queue.lease_job
    calls = {"n": 0}

    async def lease_then_client_leaves(session, worker_id, lease_seconds, **kw):
        calls["n"] += 1
        job = await real(session, worker_id, lease_seconds, **kw)
        if job is not None:
            drop.set()
            await asyncio.sleep(0.05)  # the disconnect lands before the answer is sent
        return job

    monkeypatch.setattr(queue, "lease_job", lease_then_client_leaves)
    task = asyncio.create_task(
        _drive(rig.app, {"worker_id": "leaving", "wait_seconds": 20}, None, drop=drop)
    )
    await held_count_reaches(1)
    job = await enqueue(rig)
    await asyncio.wait_for(task, timeout=5)
    assert calls["n"] >= 2
    async with rig.maker() as s:
        row = (await s.execute(select(LLMJob).where(LLMJob.id == job.id))).scalar_one()
        assert row.status == "queued" and row.attempt_count == 0
        assert row.lease_owner is None and row.attempt_id is None
    plain = await rig.post(LEASE, json={"worker_id": "next"}, headers=AUTH)
    assert plain.json()["job"]["id"] == str(job.id)
    assert plain.json()["job"]["attempt_count"] == 1


# --- a held lease is first granted a short term (review, 23-Nov-2026) -------------------
#
# A held request may be answered into a connection nobody reads (a PC asleep, a link
# dropped without a close): the watcher only sees a clean close. The job it leased is
# free again after a short first lease, not after the full term; the worker's confirm
# heartbeat extends it to the full term.


async def lease_term(client, job_id) -> tuple[float, int]:
    async with client.maker() as s:
        row = await queue.get_job(s, job_id)
        return (row.leased_until - row.heartbeat_at).total_seconds(), row.attempt_count


async def test_a_job_handed_to_a_client_that_never_reads_is_free_again_after_the_short_lease(rig):
    never = asyncio.Event()  # the client neither reads nor closes
    task = asyncio.create_task(
        _drive(rig.app, {"worker_id": "asleep", "wait_seconds": 20, "lease_seconds": 600}, None, never)
    )
    await held_count_reaches(1)
    job = await enqueue(rig)
    sent = await asyncio.wait_for(task, timeout=5)
    assert any(m.get("type") == "http.response.body" for m in sent), "answered into the void"
    term, attempts = await lease_term(rig, job.id)
    assert term == getattr(llm_jobs, "HELD_FIRST_LEASE_S", -1), f"first lease was {term}s"
    assert attempts == 1
    async with rig.maker() as s:
        row = await queue.get_job(s, job.id)
        leased_at = row.heartbeat_at
    async with rig.maker() as s:
        early = await queue.lease_job(s, "awake", 600, now=leased_at + timedelta(seconds=44))
        await s.commit()
        assert early is None
    async with rig.maker() as s:
        late = await queue.lease_job(s, "awake", 600, now=leased_at + timedelta(seconds=46))
        await s.commit()
        assert late is not None and late.id == job.id
        assert late.attempt_count == 2, "the lost answer costs one attempt, as it does today"


async def test_the_confirm_heartbeat_extends_a_short_lease_to_the_full_term(rig):
    job = await enqueue(rig)
    got = await rig.post(
        LEASE, json={"worker_id": "w1", "wait_seconds": 5, "lease_seconds": 600}, headers=AUTH
    )
    leased = got.json()["job"]
    term, _ = await lease_term(rig, job.id)
    assert term == getattr(llm_jobs, "HELD_FIRST_LEASE_S", -1)
    beat = await rig.post(
        f"/api/v1/llm-jobs/{job.id}/heartbeat",
        json={"attempt_id": leased["attempt_id"], "lease_seconds": 600},
        headers=AUTH,
    )
    assert beat.status_code == 200
    term, attempts = await lease_term(rig, job.id)
    assert term == 600 and attempts == 1


@pytest.mark.parametrize("asked", [600, None, 30])
async def test_a_plain_lease_is_still_the_full_term(rig, asked):
    job = await enqueue(rig)
    body = {"worker_id": "old-worker"}
    if asked is not None:
        body["lease_seconds"] = asked
    got = await rig.post(LEASE, json=body, headers=AUTH)
    assert got.json()["job"]["id"] == str(job.id)
    term, _ = await lease_term(rig, job.id)
    assert term == (asked or settings.llm_job_lease_seconds)


async def test_a_held_lease_never_lengthens_a_shorter_term_it_asked_for(rig):
    job = await enqueue(rig)
    await rig.post(LEASE, json={"worker_id": "w1", "wait_seconds": 5, "lease_seconds": 30}, headers=AUTH)
    term, _ = await lease_term(rig, job.id)
    assert term == 30
