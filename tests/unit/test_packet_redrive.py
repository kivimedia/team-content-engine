"""A script asked for while its request could not wait saves itself when it is written.

28-Sep-2026: he asked for a script at 10:05 UTC while the subscription worker
group was parked on its weekly limit. The request gave up at once, the job ran
and succeeded at 11:09 when capacity came back, and nothing saved it: the topic
said "no script" until someone asked again. The VPS scheduler tick (every five
minutes) now finishes such requests with no new model call, leaves jobs that are
still waiting alone, never retries a failed one, and saves each job once even
when two ticks or a tick and a person resume it together.

Synthetic data only: no worker, no provider, no network.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import tce.llm
from tce.api.routers import content_runs as runs_router
from tce.api.routers import editorial as editorial_router
from tce.api.routers import llm_jobs
from tce.editorial import inbox, lineup, notify, packets, today
from tce.editorial import status as job_status
from tce.llm import provider as llm_provider
from tce.llm import queue as llm_queue
from tce.models.content_run import WorkerGroupState
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate
from tce.models.llm_job import LLMJob
from tce.models.recording_session import RecordingSession
from tce.settings import settings
from tests.editorial_db import create_tables
from tests.unit.test_editorial_coverage_status import finish_jobs
from tests.unit.test_editorial_packets import good_output, make_candidate

KEY = "redrive-test-key"
IL = ZoneInfo("Asia/Jerusalem")
TICK = "/api/v1/content-runs/schedule/tick"


def headers(ws: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


def said_at(retry_at: datetime) -> str:
    """How the reset time reads to him: his clock, day and date."""
    local = retry_at.replace(tzinfo=UTC).astimezone(IL)
    return f"{local:%a} {local.day}-{local:%b} at {local:%H:%M}"


@pytest.fixture(autouse=True)
def clean_registry():
    job_status.clear()
    yield
    job_status.clear()


@pytest.fixture
async def sm(tmp_path):
    """File-backed SQLite: two ticks, or a tick and a person, get real separate
    connections, which the shared in-memory engine cannot give them."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'redrive.sqlite'}", poolclass=NullPool
    )
    await create_tables(engine)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
def worker(monkeypatch, sm):
    """The real durable queue on the test database. Nobody leases a job; while
    `park_until` is set, the PC worker is taken to have leased each new job and
    hit the weekly limit, which is what happened on 28-Sep."""
    monkeypatch.setattr(settings, "llm_provider", "subscription")
    state: dict = {"park_until": None}

    async def complete(req, *, wait_timeout_s=None, requeue_failed=False, **kw):
        if state["park_until"] is not None:
            async with sm() as s:
                job = await llm_queue.enqueue(s, req, requeue_failed=requeue_failed)
                if job.status == "queued":
                    job.status = "waiting_capacity"
                    job.error_code = "capacity"
                    job.retry_at = state["park_until"]
                await s.commit()
        return await llm_provider.complete(
            req,
            wait_timeout_s=0,
            sessionmaker=sm,
            poll_interval_s=0.01,
            requeue_failed=requeue_failed,
        )

    monkeypatch.setattr(tce.llm, "complete", complete)
    return state


async def park_group(sm, retry_at: datetime | None) -> None:
    async with sm() as s:
        group = (
            await s.execute(
                select(WorkerGroupState).where(
                    WorkerGroupState.group_key == llm_queue.WORKER_GROUP_KEY
                )
            )
        ).scalar_one_or_none()
        if group is None:
            group = WorkerGroupState(group_key=llm_queue.WORKER_GROUP_KEY)
            s.add(group)
        group.state = "waiting_capacity" if retry_at else "available"
        group.retry_at = retry_at
        await s.commit()


@pytest.fixture
async def client(sm, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")

    async def offline() -> dict:
        return {"workers": [], "latest": None}

    monkeypatch.setattr(llm_jobs, "get_worker_status", offline)
    app = FastAPI()
    app.include_router(runs_router.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.dependency_overrides[runs_router.get_content_sessionmaker] = lambda: sm
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sm
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


async def new_topic(sm, ws):
    async with sm() as s:
        return (await make_candidate(s, ws)).id


async def packets_of(sm, ws) -> list[RecordingPacket]:
    async with sm() as s:
        return list(
            (
                await s.execute(
                    select(RecordingPacket)
                    .where(RecordingPacket.workspace_id == ws)
                    .order_by(RecordingPacket.version)
                )
            )
            .scalars()
            .all()
        )


async def jobs_of(sm, ws) -> list[LLMJob]:
    async with sm() as s:
        return list(
            (await s.execute(select(LLMJob).where(LLMJob.workspace_id == ws))).scalars().all()
        )


async def ask_and_restart(sm, ws, cid) -> uuid.UUID:
    """A request whose wait ended with nobody leasing its job, then a restart."""
    out = await packets.build_packet(sm, ws, cid)
    assert out.status == "timeout"
    job_status.clear()
    return out.job_id


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


# ---------------------------------------------------------------------------
# The incident
# ---------------------------------------------------------------------------


async def test_a_script_asked_for_during_a_capacity_park_saves_itself_on_the_next_tick(
    sm, worker, client
):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)

    asked = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert asked.status_code == 200, asked.text
    assert await packets_of(sm, ws) == []
    (job,) = await jobs_of(sm, ws)
    assert job.status == "waiting_capacity"

    # Capacity comes back and the PC worker writes it. Nobody asks again.
    worker["park_until"] = None
    await park_group(sm, None)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())

    tick = await client.post(TICK, headers=headers(ws))
    assert tick.status_code == 200, tick.text
    saved = await packets_of(sm, ws)
    assert len(saved) == 1, "the tick saved the script that was written"
    assert saved[0].version == 1 and saved[0].status == "ready"
    assert saved[0].job_id == job.id
    assert len(await jobs_of(sm, ws)) == 1, "saved with no new model call"
    body = tick.json()
    assert [p["candidate_id"] for p in body["packets"]["redriven"]] == [str(cid)]
    assert body["packets"]["redriven"][0]["job_id"] == str(job.id)
    assert body["status"] == "redriven"

    status = (
        await client.get(f"/api/v1/editorial/candidates/{cid}/packet-status", headers=headers(ws))
    ).json()
    assert status["job"]["state"] == "done"

    # The ready-script buzz fires for it exactly as for a script saved on request.
    async with sm() as s:
        events = await notify.collect_events(s, ws)
    assert [e["dedupe_key"] for e in events if e["kind"] == "script_ready"] == [
        f"script_ready:{saved[0].id}:1"
    ]

    again = (await client.post(TICK, headers=headers(ws))).json()
    assert again["packets"]["redriven"] == []
    assert len(await packets_of(sm, ws)) == 1


async def test_a_request_ended_by_a_restart_is_saved_by_the_tick(sm, worker, client):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())

    tick = (await client.post(TICK, headers=headers(ws))).json()
    saved = await packets_of(sm, ws)
    assert len(saved) == 1 and saved[0].job_id == job_id
    assert len(await jobs_of(sm, ws)) == 1
    assert [p["candidate_id"] for p in tick["packets"]["redriven"]] == [str(cid)]


async def test_a_job_still_parked_is_left_alone_and_reported_as_waiting(sm, worker, client):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    (before,) = await jobs_of(sm, ws)

    for _ in range(2):
        tick = (await client.post(TICK, headers=headers(ws))).json()
        assert tick["packets"]["redriven"] == []
        assert tick["packets"]["waiting"] == [
            {
                "candidate_id": str(cid),
                "job_id": str(before.id),
                "job_status": "waiting_capacity",
                "retry_at": park.isoformat() + "Z",
                "reason": "waiting for capacity",
            }
        ]
    (after,) = await jobs_of(sm, ws)
    assert (after.status, after.retry_at, after.attempt_count, after.request_json) == (
        before.status,
        before.retry_at,
        before.attempt_count,
        before.request_json,
    ), "the tick never touches a job that is still waiting"
    assert await packets_of(sm, ws) == []


async def test_a_failed_job_is_reported_and_not_retried(sm, worker, client):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    async with sm() as s:
        job = await s.get(LLMJob, job_id)
        job.status, job.error_code, job.error_detail = "failed", "worker_error", "crashed"
        await s.commit()

    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert tick["packets"]["redriven"] == []
    assert [(p["candidate_id"], p["job_status"]) for p in tick["packets"]["failed"]] == [
        (str(cid), "failed")
    ]
    (job,) = await jobs_of(sm, ws)
    assert job.status == "failed" and "requeue_count" not in job.request_json
    assert await packets_of(sm, ws) == []


async def test_two_ticks_at_once_save_the_script_once(sm, worker, client):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())

    first, second = await asyncio.gather(
        client.post(TICK, headers=headers(ws)), client.post(TICK, headers=headers(ws))
    )
    redriven = first.json()["packets"]["redriven"] + second.json()["packets"]["redriven"]
    assert [p["candidate_id"] for p in redriven] == [str(cid)]
    assert len(await packets_of(sm, ws)) == 1
    assert len(await jobs_of(sm, ws)) == 1


async def test_a_tick_and_a_person_resuming_together_save_the_job_once(sm, worker, monkeypatch):
    """The rule that a job's output is saved once held only when the two saves
    took turns. Here both reach the save at the same moment, as a tick and his
    own "Prepare the script" can."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    together = asyncio.Barrier(2)
    scan = packets.scan_packet_safety

    async def scan_then_meet(*args, **kwargs):
        verdict = await scan(*args, **kwargs)
        await together.wait()  # neither saves before both are about to
        return verdict

    monkeypatch.setattr(packets, "scan_packet_safety", scan_then_meet)

    one, two = await asyncio.gather(
        packets.build_packet(sm, ws, cid, resume_job_id=job_id),
        packets.build_packet(sm, ws, cid, resume_job_id=job_id),
    )
    saved = await packets_of(sm, ws)
    assert len(saved) == 1
    assert one.packet["id"] == two.packet["id"] == str(saved[0].id)
    assert {one.status, two.status} == {"ready"}
    assert len(await jobs_of(sm, ws)) == 1


async def test_a_rewrite_waits_while_a_take_is_being_recorded_on_the_script(sm, worker, client):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    first = await packets.build_packet(sm, ws, cid)  # nobody leases it
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    v1 = await packets.build_packet(sm, ws, cid, resume_job_id=first.job_id)
    assert v1.status == "ready"
    async with sm() as s:
        # SQLite stamps to the second; the rewrite is asked for later.
        (await s.get(LLMJob, first.job_id)).created_at = utcnow() - timedelta(minutes=10)
        await s.commit()
    rewrite_job = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    async with sm() as s:
        take = RecordingSession(
            workspace_id=ws,
            candidate_id=cid,
            packet_id=uuid.UUID(v1.packet["id"]),
            packet_version=1,
            status="recording",
        )
        s.add(take)
        await s.commit()
        take_id = take.id

    held = (await client.post(TICK, headers=headers(ws))).json()
    assert held["packets"]["redriven"] == []
    assert [(p["candidate_id"], p["job_status"]) for p in held["packets"]["waiting"]] == [
        (str(cid), "succeeded")
    ]
    assert len(await packets_of(sm, ws)) == 1, "the script he is reading stays put"

    async with sm() as s:
        (await s.get(RecordingSession, take_id)).status = "finished"
        await s.commit()
    done = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in done["packets"]["redriven"]] == [str(cid)]
    saved = await packets_of(sm, ws)
    assert [p.version for p in saved] == [1, 2] and saved[1].job_id == rewrite_job


async def test_a_voice_rewrite_saved_by_the_tick_is_still_his_rewrite(sm, worker, client):
    """The call's undo reaches a rewrite by its id; the tick records it under it."""
    from tce.editorial import voice_agent

    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    first = await packets.build_packet(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    await packets.build_packet(sm, ws, cid, resume_job_id=first.job_id)
    async with sm() as s:
        (await s.get(LLMJob, first.job_id)).created_at = utcnow() - timedelta(minutes=10)
        await s.commit()
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    asked = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    rewrite_id = uuid.UUID(asked.json()["rewrite_id"])

    worker["park_until"] = None
    await park_group(sm, None)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in tick["packets"]["redriven"]] == [str(cid)]
    assert [p.version for p in await packets_of(sm, ws)] == [1, 2]
    async with sm() as s:
        assert await voice_agent.rewrite_record(s, ws, rewrite_id) is not None


async def test_a_save_that_fails_is_reported_and_not_tried_again_every_tick(
    sm, worker, client, monkeypatch
):
    """Saving a written script that fails (here the writer cited evidence from
    outside the idea) fails the same way every time, so the tick that tried says
    so, and later ticks report it without trying again every five minutes."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    await ask_and_restart(sm, ws, cid)

    def foreign(_job):
        out = good_output()
        for hook in out["hook_options"]:
            hook["moment_ids"] = ["99999999-9999-4999-8999-999999999999"]
        return out

    await finish_jobs(sm, ws, "recording_packet", foreign)
    tries: list = []
    build = editorial_router.build_packet

    async def counted(*args, **kwargs):
        tries.append(kwargs.get("resume_job_id"))
        return await build(*args, **kwargs)

    monkeypatch.setattr(editorial_router, "build_packet", counted)

    first = (await client.post(TICK, headers=headers(ws))).json()
    assert first["packets"]["redriven"] == [], "scripts_saved lists only saved scripts"
    (failed,) = first["packets"]["failed"]
    assert failed["candidate_id"] == str(cid)
    assert "outside the selected idea" in failed["reason"]

    second = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in second["packets"]["failed"]] == [str(cid)]
    assert len(tries) == 1, "tried once, not on every tick"
    assert await packets_of(sm, ws) == []

    status = (
        await client.get(f"/api/v1/editorial/candidates/{cid}/packet-status", headers=headers(ws))
    ).json()["job"]
    assert status["state"] == "failed" and "Ask for a new script" in status["current_activity"]


async def test_a_fault_in_saving_scripts_never_stops_the_tick(sm, client, monkeypatch):
    """The same tick re-drives content runs; a fault in the script half is
    reported on the cron line instead of failing the whole heartbeat."""
    ws = uuid.uuid4()

    async def broken(*_args, **_kwargs):
        raise RuntimeError("synthetic fault")

    monkeypatch.setattr(editorial_router, "redrive_packet_requests", broken, raising=False)
    tick = await client.post(TICK, headers=headers(ws))
    assert tick.status_code == 200, tick.text
    body = tick.json()
    assert body["packets"]["error"] == "RuntimeError: synthetic fault"
    assert body["packets"]["redriven"] == [] and body["redriven"] == []
    assert body["status"] == "disabled_or_not_due"


# ---------------------------------------------------------------------------
# What he is told while it waits
# ---------------------------------------------------------------------------


def test_the_reset_time_reads_as_his_clock():
    assert job_status.israel_time(datetime(2026, 9, 30, 4, 0)) == "Wed 30-Sep at 07:00"
    # Winter time is UTC+2.
    assert job_status.israel_time(datetime(2026, 12, 2, 5, 0)) == "Wed 2-Dec at 07:00"


async def test_a_parked_request_says_it_waits_for_capacity_and_saves_itself(sm, worker, client):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    asked = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert said_at(park) in asked.json()["said"]

    entry = job_status.get(ws, "packet", str(cid))
    words = f"{entry['current_activity']} {entry['detail']}"
    assert entry["state"] == "waiting"
    assert "Claude limit" in words and said_at(park) in words and "saves itself" in words

    for restarted in (False, True):
        if restarted:
            job_status.clear()
        status = (
            await client.get(
                f"/api/v1/editorial/candidates/{cid}/packet-status", headers=headers(ws)
            )
        ).json()["job"]
        assert status["state"] == "waiting", status
        assert said_at(park) in status["current_activity"]
        assert "saves itself" in status["current_activity"]
        assert "Retry" not in status["current_activity"]
        assert "interrupted" not in status["current_activity"]


async def test_a_queued_job_behind_a_parked_worker_says_it_waits_for_capacity(sm, worker):
    """The wait can also end on the clock: a new job is never leased while the
    worker group is parked, so it sits queued. It is still waiting for capacity."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    park = utcnow() + timedelta(days=2)
    await park_group(sm, park)
    out = await packets.build_packet(sm, ws, cid)
    assert out.status == "timeout"
    job_status.clear()
    async with sm() as s:
        view = await job_status.latest_packet_job(s, ws, cid)
    assert view["state"] == "waiting" and view["resumable"] is True
    assert said_at(park) in view["current_activity"] and "saves itself" in view["current_activity"]


async def test_a_script_being_written_is_not_said_to_wait_for_the_limit(sm, worker):
    """A job the worker has already taken is being written; the parked group
    holds back only the jobs it has not taken yet."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    async with sm() as s:
        (await s.get(LLMJob, job_id)).status = "leased"
        await s.commit()
    await park_group(sm, utcnow() + timedelta(days=2))
    async with sm() as s:
        view = await job_status.latest_packet_job(s, ws, cid)
    assert view["state"] == "waiting" and view["resumable"] is True
    assert "Claude limit" not in view["current_activity"]
    assert "saves itself" in view["current_activity"]


async def test_undoing_a_rewrite_still_on_its_way_says_it_is_coming(sm, worker, client):
    """The call's undo said "never saved, nothing to undo" for a rewrite that
    the tick now saves when it is written."""
    from tce.editorial import voice_agent

    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    first = await packets.build_packet(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    await packets.build_packet(sm, ws, cid, resume_job_id=first.job_id)
    async with sm() as s:
        (await s.get(LLMJob, first.job_id)).created_at = utcnow() - timedelta(minutes=10)
        await s.commit()
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    asked = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    rewrite_id = uuid.UUID(asked.json()["rewrite_id"])

    async with sm() as s:
        with pytest.raises(voice_agent.VoiceError) as caught:
            await voice_agent.undo_rewrite(s, ws, cid, rewrite_id, replaced_version=1)
    assert caught.value.code == "still_writing", caught.value.message
    assert said_at(park) in caught.value.message and "saves itself" in caught.value.message
    assert "never saved" not in caught.value.message


async def test_a_written_script_waiting_for_the_tick_says_it_is_being_saved(sm, worker):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    async with sm() as s:
        view = await job_status.latest_packet_job(s, ws, cid)
    assert view["state"] == "waiting" and view["resumable"] is True
    assert "saved within five minutes" in view["current_activity"]
    assert "never saved" not in view["current_activity"]


async def test_the_week_today_and_the_topic_say_the_script_is_coming(sm, worker):
    """No dead end: the card does not offer "Prepare the script" again, and
    Today does not send him to prepare a script that is already on its way."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    await packets.build_packet(sm, ws, cid)
    async with sm() as s:
        week = await lineup.current_lineup(s, ws)
        await lineup.add_topic(s, ws, week, await s.get(TopicCandidate, cid))
        await s.commit()

    async with sm() as s:
        data = await today.build(s, ws)
        room = await inbox.topic_room(s, ws, cid)
    (item,) = data["week"]["primary"]
    assert item["script_state"] == "none"
    request = item["script_request"]
    assert request["state"] == "waiting_capacity" and request["pending"] is True
    assert said_at(park) in request["sentence"] and "saves itself" in request["sentence"]
    action = data["next_action"]
    assert action["key"] == "scripts_coming", action
    assert said_at(park) in action["detail"]
    assert room["script"] is None and room["script_request"]["pending"] is True
    assert room["script_note"] == request["sentence"]


async def test_a_topic_never_asked_for_still_offers_the_script(sm):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    async with sm() as s:
        week = await lineup.current_lineup(s, ws)
        await lineup.add_topic(s, ws, week, await s.get(TopicCandidate, cid))
        await s.commit()
    async with sm() as s:
        data = await today.build(s, ws)
        room = await inbox.topic_room(s, ws, cid)
    (item,) = data["week"]["primary"]
    assert item["script_request"] is None
    assert data["next_action"]["key"] == "prepare_scripts"
    assert room["script_request"] is None
    assert "PC worker" in room["script_note"]


# ---------------------------------------------------------------------------
# The cron line
# ---------------------------------------------------------------------------


def tick_line(tmp_path: Path, body: dict) -> str:
    """The line the cron script writes to its log for this tick answer."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "tce-schedule-tick.sh"
    summary = re.search(r"<<'PY'.*?\n(.*?)\nPY\n", script.read_text(encoding="utf-8"), re.S)
    assert summary is not None
    path = tmp_path / "tick-body.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-", str(path)],
        input=summary.group(1),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_the_tick_log_line_names_the_scripts_it_saved_and_the_ones_waiting(tmp_path):
    body = {
        "status": "redriven",
        "occurrences": [],
        "redriven": [],
        "worker": {"online": False, "detail": "offline"},
        "packets": {
            "redriven": [{"candidate_id": "aaaaaaaa-1111-2222-3333-444444444444", "job_id": "j"}],
            "waiting": [
                {
                    "candidate_id": "bbbbbbbb-1111-2222-3333-444444444444",
                    "job_id": "j2",
                    "job_status": "waiting_capacity",
                    "retry_at": "2026-09-30T04:00:00Z",
                }
            ],
            "failed": [],
        },
    }
    line = tick_line(tmp_path, body)
    assert "scripts_saved=[aaaaaaaa]" in line
    assert "scripts_waiting=[bbbbbbbb@waiting_capacity]" in line
    assert "scripts_failed=[]" in line
    assert "scripts_error" not in line

    body["packets"] = {"redriven": [], "waiting": [], "failed": [], "error": "OperationalError: x"}
    assert "scripts_error=(OperationalError: x)" in tick_line(tmp_path, body)


# ---------------------------------------------------------------------------
# Review of the first cut (28-Sep): a save that raises, an old ask, a fault
# in the tick itself, and a topic filmed while its new script waited
# ---------------------------------------------------------------------------


def locked(statement: str = "UPDATE topic_candidates") -> OperationalError:
    """What a save meets when the database is busy for a moment: SQLite's
    "database is locked", a PostgreSQL lock timeout or a dropped connection."""
    return OperationalError(statement, {}, Exception("database is locked"))


async def test_a_save_that_raises_is_tried_again_by_the_next_tick(sm, worker, client, monkeypatch):
    """A lock or a dropped connection says nothing about the script. It used to
    mark the written script unsaveable for good: the tick stopped trying, and
    his "Prepare the script" paid for a new model call to write it again."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    build = editorial_router.build_packet
    tries: list = []

    async def locked_once(*args, **kwargs):
        tries.append(kwargs.get("resume_job_id"))
        if len(tries) == 1:
            raise locked()
        return await build(*args, **kwargs)

    monkeypatch.setattr(editorial_router, "build_packet", locked_once)
    first = (await client.post(TICK, headers=headers(ws))).json()
    assert first["packets"]["redriven"] == []
    assert [(p["candidate_id"], p["reason"]) for p in first["packets"]["failed"]] == [
        (str(cid), "OperationalError")
    ]
    async with sm() as s:
        view = await job_status.latest_packet_job(s, ws, cid)
    assert view["state"] == "waiting" and view["resumable"] is True, view
    assert "saved within five minutes" in view["current_activity"]

    second = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in second["packets"]["redriven"]] == [str(cid)]
    saved = await packets_of(sm, ws)
    assert len(saved) == 1 and saved[0].job_id == job_id
    assert len(await jobs_of(sm, ws)) == 1, "saved with no new model call"


async def test_his_ask_after_a_save_that_raised_saves_the_written_script(
    sm, worker, client, monkeypatch
):
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    build = editorial_router.build_packet
    tries: list = []

    async def locked_once(*args, **kwargs):
        tries.append(kwargs.get("resume_job_id"))
        if len(tries) == 1:
            raise locked()
        return await build(*args, **kwargs)

    monkeypatch.setattr(editorial_router, "build_packet", locked_once)
    await client.post(TICK, headers=headers(ws))

    asked = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert asked.status_code == 200, asked.text
    assert asked.json()["resumed"] is True
    assert len(await jobs_of(sm, ws)) == 1, "his ask spent no new model call"
    saved = await packets_of(sm, ws)
    assert len(saved) == 1 and saved[0].job_id == job_id


async def test_a_save_that_keeps_raising_is_tried_three_times_then_offered_back(
    sm, worker, client, monkeypatch
):
    """Something that raises every time (a bug, not a lock) is not tried every
    five minutes for ever, and nothing keeps promising it saves itself: the
    button comes back, and pressing it still saves the written script."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    tries: list = []

    async def always_locked(*args, **kwargs):
        tries.append(kwargs.get("resume_job_id"))
        raise locked()

    monkeypatch.setattr(editorial_router, "build_packet", always_locked)
    for _ in range(5):
        last = (await client.post(TICK, headers=headers(ws))).json()
    assert len(tries) == 3, tries
    (failed,) = last["packets"]["failed"]
    assert failed["candidate_id"] == str(cid) and "3 times" in failed["reason"], failed

    async with sm() as s:
        room = await inbox.topic_room(s, ws, cid)
        view = await job_status.latest_packet_job(s, ws, cid)
    request = room["script_request"]
    assert request["pending"] is False, request
    assert "without a new model call" in request["sentence"], request
    assert "saved within five minutes" not in request["sentence"]
    assert view["resumable"] is True

    asked = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert asked.status_code == 200 and asked.json()["resumed"] is True, asked.text
    assert len(await jobs_of(sm, ws)) == 1


async def test_more_openings_are_asked_for_once_the_new_script_stops_coming(sm, worker, client):
    """While a new script is on its way, more openings for the old one are
    refused: the new one replaces it when it saves itself. When its job fails
    nothing is on its way, and the refusal ("It saves itself") would be false
    for as long as the process runs."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    first = await packets.build_packet(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    v1 = await packets.build_packet(sm, ws, cid, resume_job_id=first.job_id)
    async with sm() as s:
        (await s.get(LLMJob, first.job_id)).created_at = utcnow() - timedelta(minutes=10)
        await s.commit()
    asked = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True},
        headers=headers(ws),
    )
    assert asked.status_code == 200, asked.text
    more = f"/api/v1/editorial/packets/{v1.packet['id']}/more-hooks"

    coming = await client.post(more, headers=headers(ws))
    assert coming.status_code == 409, coming.text
    assert coming.json()["detail"]["code"] == "still_writing"
    assert "saves itself" in coming.json()["detail"]["message"]

    rewrite = max(await jobs_of(sm, ws), key=lambda j: j.created_at)
    async with sm() as s:
        job = await s.get(LLMJob, rewrite.id)
        job.status, job.error_code = "failed", "worker_error"
        await s.commit()
    await client.post(TICK, headers=headers(ws))

    stopped = await client.post(more, headers=headers(ws))
    assert stopped.status_code == 202, stopped.text
    assert job_status.get(ws, "more_hooks", v1.packet["id"]) is not None


async def test_a_script_asked_for_more_than_eight_days_ago_saves_itself_when_written(
    sm, worker, client
):
    """A weekly park and a few days with the PC away: the job is written nine
    days after it was asked for. It was never saved, while the topic promised
    it within five minutes and hid the button."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    async with sm() as s:
        (await s.get(LLMJob, job_id)).created_at = utcnow() - timedelta(days=9)
        await s.commit()
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())

    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in tick["packets"]["redriven"]] == [str(cid)]
    saved = await packets_of(sm, ws)
    assert len(saved) == 1 and saved[0].job_id == job_id
    assert len(await jobs_of(sm, ws)) == 1


async def test_a_script_written_long_ago_and_never_saved_is_offered_not_promised(
    sm, worker, client
):
    """The tick finishes what moved in the last eight days. A script written
    and left unsaved before that is not saved by the clock days later, so
    nothing may promise it: the button comes back, and pressing it saves the
    written script with no new model call."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    long_ago = utcnow() - timedelta(days=10)
    async with sm() as s:
        job = await s.get(LLMJob, job_id)
        job.created_at, job.completed_at, job.updated_at = long_ago, long_ago, long_ago
        await s.commit()

    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert tick["packets"] == {"redriven": [], "waiting": [], "failed": []}
    async with sm() as s:
        room = await inbox.topic_room(s, ws, cid)
        view = await job_status.latest_packet_job(s, ws, cid)
    request = room["script_request"]
    assert request["pending"] is False, request
    assert "without a new model call" in request["sentence"], request
    assert room["script_note"] == request["sentence"]
    assert view["resumable"] is True and "five minutes" not in view["current_activity"]

    asked = await client.post(f"/api/v1/editorial/candidates/{cid}/packet", headers=headers(ws))
    assert asked.status_code == 200 and asked.json()["resumed"] is True, asked.text
    saved = await packets_of(sm, ws)
    assert len(saved) == 1 and saved[0].job_id == job_id
    assert len(await jobs_of(sm, ws)) == 1


async def test_a_fault_on_one_script_does_not_strand_the_one_claimed_before_it(
    sm, worker, client, monkeypatch
):
    """The tick claims each written script, then saves them. A lookup that
    raised on the second one used to leave the first claimed ("being saved")
    for as long as the process ran: never saved, and his own ask refused with
    "packet already being written"."""
    from tce.editorial import voice_agent

    ws = uuid.uuid4()
    first_topic = await new_topic(sm, ws)
    second_topic = await new_topic(sm, ws)
    first_job = await ask_and_restart(sm, ws, first_topic)
    async with sm() as s:
        (await s.get(LLMJob, first_job)).created_at = utcnow() - timedelta(minutes=10)
        await s.commit()
    await ask_and_restart(sm, ws, second_topic)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    # The second one carries a voice rewrite asked for earlier in this process,
    # so the tick looks up its script before claiming it.
    job_status.start(ws, "packet", str(second_topic), "Waiting", rewrite_id=str(uuid.uuid4()))
    job_status.update(ws, "packet", str(second_topic), state="waiting")
    real = voice_agent.current_packet
    calls: list = []

    async def blip(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise locked("SELECT recording_packets")
        return await real(*args, **kwargs)

    monkeypatch.setattr(voice_agent, "current_packet", blip)
    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in tick["packets"]["redriven"]] == [str(first_topic)]
    assert [(p["candidate_id"], p["reason"]) for p in tick["packets"]["failed"]] == [
        (str(second_topic), "OperationalError")
    ]
    assert not job_status.is_running(ws, "packet", str(second_topic))

    again = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in again["packets"]["redriven"]] == [str(second_topic)]
    assert {p.candidate_id for p in await packets_of(sm, ws)} == {first_topic, second_topic}
    assert len(await jobs_of(sm, ws)) == 2


async def test_a_fault_after_the_tick_claimed_a_script_releases_it(sm, worker, client, monkeypatch):
    """Whatever stops the tick between claiming a script and saving it (here
    the listing's session failing as it closes), the claim is let go, so the
    next tick saves it and his own ask is not refused."""
    from contextlib import asynccontextmanager

    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    job_id = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())

    @asynccontextmanager
    async def drops_on_close(source):
        async with source() as session:
            yield session
        raise locked("COMMIT")

    real = editorial_router.open_session
    monkeypatch.setattr(editorial_router, "open_session", drops_on_close)
    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert tick["packets"]["error"].startswith("OperationalError"), tick["packets"]
    monkeypatch.setattr(editorial_router, "open_session", real)

    assert not job_status.is_running(ws, "packet", str(cid))
    status = (
        await client.get(f"/api/v1/editorial/candidates/{cid}/packet-status", headers=headers(ws))
    ).json()["job"]
    assert status["state"] == "waiting" and "five minutes" in status["current_activity"], status

    again = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in again["packets"]["redriven"]] == [str(cid)]
    saved = await packets_of(sm, ws)
    assert len(saved) == 1 and saved[0].job_id == job_id


async def film(sm, ws, cid, packet_id, *, at: datetime | None = None) -> None:
    """A take on this script that the pipeline made something of: filmed."""
    async with sm() as s:
        take = RecordingUpload(
            workspace_id=ws,
            candidate_id=cid,
            packet_id=uuid.UUID(str(packet_id)),
            original_filename="take.mp4",
            storage_path="/tmp/take.mp4",
            sha256=uuid.uuid4().hex * 2,
            status="transcribed",
            transcript=[{"w": "hello"}],
        )
        if at is not None:
            take.created_at = at
        s.add(take)
        (await s.get(TopicCandidate, cid)).status = "recorded"
        await s.commit()


async def scripted_topic(sm, ws):
    """A topic with version 1 saved, asked for a while ago."""
    cid = await new_topic(sm, ws)
    first = await packets.build_packet(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    v1 = await packets.build_packet(sm, ws, cid, resume_job_id=first.job_id)
    async with sm() as s:
        (await s.get(LLMJob, first.job_id)).created_at = utcnow() - timedelta(days=2)
        await s.commit()
    return cid, v1


async def test_a_rewrite_is_kept_aside_when_he_films_the_script_after_asking(sm, worker, client):
    """Asked for a new script on Monday while the worker was parked; filmed the
    old one on Tuesday; the new one was written on Wednesday. The tick saved it
    over the script he filmed and buzzed "Your script is ready" for a topic
    already filmed. The script he filmed stays; the new one waits for him."""
    ws = uuid.uuid4()
    cid, v1 = await scripted_topic(sm, ws)
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    asked = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True, "by": "voice"},
        headers=headers(ws),
    )
    assert asked.status_code == 200, asked.text
    rewrite = max(await jobs_of(sm, ws), key=lambda j: j.created_at)
    async with sm() as s:
        (await s.get(LLMJob, rewrite.id)).created_at = utcnow() - timedelta(days=1)
        await s.commit()
    await film(sm, ws, cid, v1.packet["id"])

    worker["park_until"] = None
    await park_group(sm, None)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())
    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert tick["packets"]["redriven"] == []
    (held,) = tick["packets"]["failed"]
    assert held["candidate_id"] == str(cid) and "filmed" in held["reason"], held

    saved = await packets_of(sm, ws)
    assert [(p.version, p.status) for p in saved] == [(1, "ready")], "the filmed script stays"
    async with sm() as s:
        events = await notify.collect_events(s, ws)
        room = await inbox.topic_room(s, ws, cid)
        view = await job_status.latest_packet_job(s, ws, cid)
    assert [e["dedupe_key"] for e in events if e["kind"] == "script_ready"] == [
        f"script_ready:{v1.packet['id']}:1"
    ], "no buzz for a script over one he filmed"
    assert room["script"]["version"] == 1 and room["script_request"] is None
    assert "filmed" in view["current_activity"] and view["resumable"] is True

    again = (await client.post(TICK, headers=headers(ws))).json()
    assert again["packets"]["redriven"] == [] and len(await packets_of(sm, ws)) == 1


async def test_a_rewrite_asked_for_after_filming_is_saved_as_usual(sm, worker, client):
    """Filming first and then asking for a new script (to film it again) is
    the other order: that ask is the newer word, and the tick saves it."""
    ws = uuid.uuid4()
    cid, v1 = await scripted_topic(sm, ws)
    await film(sm, ws, cid, v1.packet["id"], at=utcnow() - timedelta(days=1))
    rewrite_job = await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: good_output())

    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert [p["candidate_id"] for p in tick["packets"]["redriven"]] == [str(cid)]
    saved = await packets_of(sm, ws)
    assert [p.version for p in saved] == [1, 2] and saved[1].job_id == rewrite_job


def broken_output() -> dict:
    """What the model sent back three times on 20-Sep: fewer beats than bullets."""
    out = good_output()
    out["beats"] = out["beats"][:1]
    return out


async def test_a_rewrite_that_came_back_broken_over_a_ready_script_is_not_a_failure(
    sm, worker, client
):
    """28-Sep, the first tick after deploy listed two topics as failed scripts
    while each had a ready script: a rewrite from 20-Sep had come back broken.
    The week says nothing about a rewrite that stopped (the script he has
    stands), so the tick says nothing either."""
    ws = uuid.uuid4()
    cid, _v1 = await scripted_topic(sm, ws)
    await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: broken_output())

    tick = (await client.post(TICK, headers=headers(ws))).json()
    assert tick["packets"]["failed"] == [], tick["packets"]
    assert tick["packets"]["redriven"] == []
    assert [p.version for p in await packets_of(sm, ws)] == [1]


async def test_a_script_that_came_back_broken_says_so_in_plain_words(sm, worker, client):
    """The only script asked for came back broken. The week and the tick say
    so, in his words, not the validator's."""
    ws = uuid.uuid4()
    cid = await new_topic(sm, ws)
    await ask_and_restart(sm, ws, cid)
    await finish_jobs(sm, ws, "recording_packet", lambda _job: broken_output())

    tick = (await client.post(TICK, headers=headers(ws))).json()
    (failed,) = tick["packets"]["failed"]
    assert failed["candidate_id"] == str(cid)
    async with sm() as s:
        request = (await job_status.packet_requests(s, ws, [cid]))[cid]
    for said in (failed["reason"], request["sentence"]):
        assert "validation" not in said and "packet" not in said.lower(), said
        assert "Ask for a new script" in said, said


async def test_the_week_and_the_topic_say_a_new_script_is_on_its_way(sm, worker, client):
    """The week showed the old script as ready with nothing about the new one
    coming to replace it, so he could not know that filming it now keeps the
    new one aside."""
    ws = uuid.uuid4()
    cid, _v1 = await scripted_topic(sm, ws)
    async with sm() as s:
        week = await lineup.current_lineup(s, ws)
        await lineup.add_topic(s, ws, week, await s.get(TopicCandidate, cid))
        await s.commit()
    park = utcnow() + timedelta(days=2)
    worker["park_until"] = park
    await park_group(sm, park)
    asked = await client.post(
        f"/api/v1/editorial/candidates/{cid}/packet",
        json={"replace": True},
        headers=headers(ws),
    )
    assert asked.status_code == 200, asked.text

    async with sm() as s:
        data = await today.build(s, ws)
        room = await inbox.topic_room(s, ws, cid)
    (item,) = data["week"]["primary"]
    assert item["script_state"] == "ready"
    request = item["script_request"]
    assert request is not None and request["pending"] is True, item
    assert request["label"] == "New script on its way"
    assert said_at(park) in request["sentence"]
    assert "film this script first" in request["sentence"], request
    assert room["script"]["version"] == 1
    assert room["script_request"] == request
