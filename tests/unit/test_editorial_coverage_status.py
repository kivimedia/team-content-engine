"""Editorial follow-up: full weekly coverage, Israel-time week windows, durable status.

Synthetic fixtures only.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

import tce.llm
from tce.editorial import packets, selector
from tce.editorial import status as job_status
from tce.editorial.common import current_week_start, week_bounds, week_source_window
from tce.llm import LLMResult, LLMUnavailable
from tce.llm import provider as llm_provider
from tce.models.editorial import (
    REJECTION_GATES,
    EvidenceMoment,
    EvidenceSource,
    RecordingPacket,
    TopicCandidate,
)
from tce.models.llm_job import LLMJob
from tce.settings import settings

WEEK = date(2026, 9, 7)
_IDS = re.compile(r'"moment_id": "([0-9a-f-]{36})"')


def gates_all_pass() -> dict:
    return {g: {"pass": True, "reason": f"synthetic reason for {g}"} for g in REJECTION_GATES}


async def add_source(session, ws, *, occurred_at, kind="fathom_meeting"):
    src = EvidenceSource(
        workspace_id=ws,
        source_kind=kind,
        external_id=str(uuid.uuid4()),
        title="Synthetic source",
        occurred_at=occurred_at,
        version_hash="a" * 64,
        fetch_status="ok",
        payload_private={},
    )
    session.add(src)
    await session.flush()
    return src


async def add_moments(session, ws, src, n, lesson="synthetic lesson"):
    out = []
    for i in range(n):
        m = EvidenceMoment(
            workspace_id=ws,
            source_id=src.id,
            source_version_hash="a" * 64,
            speaker_confidence="high",
            excerpt_private=f"synthetic excerpt {i}",
            lesson_summary=f"{lesson} {i}",
            claim_type="paraphrased",
            sensitivity_flags=[],
        )
        session.add(m)
        out.append(m)
    await session.commit()
    return out


def candidate_for(moment_id, title) -> dict:
    return {
        "moment_ids": [str(moment_id)],
        "title": title,
        "lesson": "Name the problems in order before choosing lessons.",
        "audience": "coaches",
        "public_angle": "A question to ask before planning any course.",
        "gates": gates_all_pass(),
        "scores": {"owner_relevance": 5, "useful_lesson": 5, "support_strength": 4},
    }


def ids_in(req) -> list[str]:
    return _IDS.findall(req.messages[0]["content"])


@pytest.fixture
def judge(monkeypatch):
    """Fake subscription job: proposes a candidate for `strong` ids, rejects the rest."""
    state: dict = {"strong": set(), "calls": [], "skip": set(), "raise_for": None, "extra": []}

    async def fake_complete(req, *, wait_timeout_s=None, **kw):
        state["calls"].append(req)
        ids = ids_in(req)
        if state["raise_for"] and state["raise_for"] in ids:
            raise LLMUnavailable("waiting_capacity", "limit reached", job_id=uuid.uuid4())
        cands = [candidate_for(i, f"Strong idea {i[:6]}") for i in ids if i in state["strong"]]
        rejs = [
            {"moment_ids": [i], "gate": "concrete_supported_substance", "reason": "thin"}
            for i in ids
            if i not in state["strong"] and i not in state["skip"]
        ] + state["extra"]
        return LLMResult(
            job_id=uuid.uuid4(),
            text="",
            structured={"candidates": cands, "rejections": rejs},
            model="claude-opus-5",
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    return state


async def rows_for(sm, ws):
    async with sm() as s:
        return (
            (await s.execute(select(TopicCandidate).where(TopicCandidate.workspace_id == ws)))
            .scalars()
            .all()
        )


# ---------------------------------------------------------------------------
# 1. Coverage
# ---------------------------------------------------------------------------


async def test_busy_late_week_cannot_hide_an_earlier_strong_lesson(editorial_sessionmaker, judge):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        early_src = await add_source(s, ws, occurred_at=datetime(2026, 9, 7, 6))
        (early,) = await add_moments(s, ws, early_src, 1, "the strong early lesson")
        late = []
        for h in range(9):  # a busy repository and meetings late in the week
            src = await add_source(
                s, ws, occurred_at=datetime(2026, 9, 13, 10 + h), kind="github_commit_group"
            )
            late += await add_moments(s, ws, src, 10)
    judge["strong"] = {str(early.id)}

    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)

    all_week = {str(early.id)} | {str(m.id) for m in late}
    assert len(all_week) == 91 > 60
    sent = [i for req in judge["calls"] for i in ids_in(req)]
    assert sorted(sent) == sorted(all_week)  # every moment exactly once, no truncation
    assert len(judge["calls"]) == 3
    assert all(len(ids_in(r)) <= selector.SHARD_SIZE for r in judge["calls"])
    assert {r.idempotency_key for r in judge["calls"]} == {
        f"editorial_selection:{ws}:{res.selection_run_id}:shard:{i}/3" for i in (1, 2, 3)
    }

    assert res.status == "complete"
    assert [c["moment_ids"] for c in res.candidates] == [[str(early.id)]]
    cov = res.to_dict()["coverage"]
    assert cov["week_moments"] == 91 and cov["considered"] == 91
    assert cov["unaccounted_moment_ids"] == [] and cov["complete"] is True
    assert [sh["status"] for sh in cov["shards"]] == ["succeeded"] * 3
    assert sum(sh["accounted"] for sh in cov["shards"]) == 91


async def test_no_quota_padding_across_shards(editorial_sessionmaker, judge):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        for d in range(7):
            src = await add_source(s, ws, occurred_at=datetime(2026, 9, 7 + d, 9))
            ms = await add_moments(s, ws, src, 12)
    judge["strong"] = {str(ms[0].id)}
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK, max_candidates=6)
    assert len(judge["calls"]) >= 2
    assert len(res.candidates) == 1
    rows = await rows_for(editorial_sessionmaker, ws)
    assert sum(1 for r in rows if r.status == "proposed") == 1


async def test_skipped_moments_are_reported_not_invented_as_rejections(
    editorial_sessionmaker, judge
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        src = await add_source(s, ws, occurred_at=datetime(2026, 9, 9, 9))
        ms = await add_moments(s, ws, src, 5)
    judge["skip"] = {str(ms[1].id), str(ms[3].id)}
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    cov = res.coverage
    assert sorted(cov["unaccounted_moment_ids"]) == sorted(judge["skip"])
    assert cov["complete"] is False and "not accounted" in res.detail
    rejected_ids = {i for r in await rows_for(editorial_sessionmaker, ws) for i in r.moment_ids}
    assert rejected_ids.isdisjoint(judge["skip"])
    assert len(rejected_ids) == 3


async def test_one_unfinished_shard_saves_nothing_and_keeps_prior_proposals(
    editorial_sessionmaker, judge
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        srcs = []
        for d in range(3):
            src = await add_source(s, ws, occurred_at=datetime(2026, 9, 8 + d, 9))
            srcs.append(await add_moments(s, ws, src, 30))
    judge["strong"] = {str(srcs[0][0].id)}
    await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    before = [(r.id, r.status) for r in await rows_for(editorial_sessionmaker, ws)]

    judge["raise_for"] = str(srcs[2][0].id)
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert res.status == "waiting_capacity"
    assert res.candidates == [] and res.rejected == []
    states = sorted(sh["status"] for sh in res.coverage["shards"])
    assert "waiting_capacity" in states and "succeeded" in states
    assert "nothing was saved" in res.detail
    after = [(r.id, r.status) for r in await rows_for(editorial_sessionmaker, ws)]
    assert after == before  # not rejected, not superseded


async def test_rejections_citing_other_tenants_are_not_persisted(editorial_sessionmaker, judge):
    ws, other = uuid.uuid4(), uuid.uuid4()
    async with editorial_sessionmaker() as s:
        src = await add_source(s, ws, occurred_at=datetime(2026, 9, 9, 9))
        await add_moments(s, ws, src, 3)
        osrc = await add_source(s, other, occurred_at=datetime(2026, 9, 9, 9))
        (foreign,) = await add_moments(s, other, osrc, 1)
    judge["extra"] = [{"moment_ids": [str(foreign.id)], "gate": "x", "reason": "guess"}]
    res = await selector.select_candidates(editorial_sessionmaker, ws, WEEK)
    assert all(str(foreign.id) not in ids_in(r) for r in judge["calls"])
    assert res.coverage["shards"][0]["rejections_dropped"] == 1
    for r in await rows_for(editorial_sessionmaker, ws):
        assert str(foreign.id) not in r.moment_ids
    assert await rows_for(editorial_sessionmaker, other) == []


async def test_reserve_is_bounded_diverse_and_reported(editorial_session):
    ws = uuid.uuid4()
    s = editorial_session
    busy = await add_source(s, ws, occurred_at=datetime(2026, 8, 30, 9))
    await add_moments(s, ws, busy, 45)
    quiet = await add_source(s, ws, occurred_at=datetime(2026, 8, 10, 9))
    quiet_ms = await add_moments(s, ws, quiet, 5)
    plan = await selector.collect_pool(s, ws, WEEK)
    assert plan.week_total == 0
    assert plan.reserve_eligible == 50 and plan.reserve_included == selector.RESERVE_POOL_LIMIT
    picked = {pm.id for pm in plan.moments}
    assert {str(m.id) for m in quiet_ms} <= picked  # the older source is not crowded out


def test_plan_shards_keeps_sources_together_and_loses_nothing():
    class Src:
        def __init__(self, t):
            self.id = uuid.uuid4()
            self.occurred_at = t

    class Mom:
        def __init__(self):
            self.id = uuid.uuid4()
            self.created_at = None

    pool = []
    for i, size in enumerate([5, 30, 12, 50, 3]):
        src = Src(datetime(2026, 9, 7) + timedelta(hours=i))
        pool += [selector.PoolMoment(Mom(), src, True) for _ in range(size)]
    shards = selector.plan_shards(pool, 40)
    flat = [pm.id for sh in shards for pm in sh]
    assert sorted(flat) == sorted(pm.id for pm in pool)
    assert all(len(sh) <= 40 for sh in shards)
    split = {
        str(pm.source.id)
        for pm in pool
        if sum(str(pm.source.id) == str(x.source.id) for x in pool) <= 40
    }
    for sid in split:  # a source that fits in one shard is never split
        assert sum(any(str(pm.source.id) == sid for pm in sh) for sh in shards) == 1


# ---------------------------------------------------------------------------
# 2. Week window in Israel time, label unchanged
# ---------------------------------------------------------------------------


def test_week_windows_follow_israel_time_across_dst():
    assert week_source_window(WEEK) == (datetime(2026, 9, 6, 21), datetime(2026, 9, 13, 21))
    assert week_source_window("2026-01-05") == (datetime(2026, 1, 4, 22), datetime(2026, 1, 11, 22))
    # week in which summer time ends (25 Oct 2026) and starts (27 Mar 2026)
    assert week_source_window("2026-10-19") == (
        datetime(2026, 10, 18, 21),
        datetime(2026, 10, 25, 22),
    )
    assert week_source_window("2026-03-23") == (
        datetime(2026, 3, 22, 22),
        datetime(2026, 3, 29, 21),
    )
    assert week_bounds("2026-09-07")[0] == datetime(2026, 9, 7)  # storage label unchanged
    assert current_week_start(date(2026, 9, 13)) == date(2026, 9, 7)


@pytest.mark.parametrize(
    ("week", "inside", "outside"),
    [
        (
            date(2026, 9, 7),
            [datetime(2026, 9, 6, 21, 0), datetime(2026, 9, 13, 20, 59)],
            [datetime(2026, 9, 6, 20, 59), datetime(2026, 9, 13, 21, 0)],
        ),
        (
            date(2026, 1, 5),
            [datetime(2026, 1, 4, 22, 0), datetime(2026, 1, 11, 21, 59)],
            [datetime(2026, 1, 4, 21, 59), datetime(2026, 1, 11, 22, 0)],
        ),
    ],
)
async def test_source_filtering_uses_israel_week_and_keeps_label(
    editorial_sessionmaker, judge, week, inside, outside
):
    ws = uuid.uuid4()
    ins, outs = [], []
    async with editorial_sessionmaker() as s:
        for t in inside:
            ins += await add_moments(s, ws, await add_source(s, ws, occurred_at=t), 1)
        for t in outside:
            outs += await add_moments(s, ws, await add_source(s, ws, occurred_at=t), 1)
        plan = await selector.collect_pool(s, ws, week)
    week_ids = {pm.id for pm in plan.moments if pm.in_week}
    assert week_ids == {str(m.id) for m in ins}
    # the moment just before the window is evergreen reserve, the one after is excluded
    assert {pm.id for pm in plan.moments if not pm.in_week} == {str(outs[0].id)}

    judge["strong"] = {str(ins[0].id)}
    res = await selector.select_candidates(editorial_sessionmaker, ws, week)
    rows = await rows_for(editorial_sessionmaker, ws)
    assert {r.week_start for r in rows} == {datetime(week.year, week.month, week.day)}
    assert res.candidates[0]["week_start"].startswith(week.isoformat())


# ---------------------------------------------------------------------------
# 3. Durable status and safe resume
# ---------------------------------------------------------------------------


@pytest.fixture
def real_queue(monkeypatch, editorial_sessionmaker):
    """The real durable queue on the test database; nobody leases, so waits time out."""
    monkeypatch.setattr(settings, "llm_provider", "subscription")

    async def complete(req, *, wait_timeout_s=None, **kw):
        return await llm_provider.complete(
            req, wait_timeout_s=0, sessionmaker=editorial_sessionmaker, poll_interval_s=0.01, **kw
        )

    monkeypatch.setattr(tce.llm, "complete", complete)
    job_status.clear()
    yield
    job_status.clear()


async def finish_jobs(sm, ws, job_type, make_output):
    async with sm() as s:
        jobs = (
            (
                await s.execute(
                    select(LLMJob).where(LLMJob.workspace_id == ws, LLMJob.job_type == job_type)
                )
            )
            .scalars()
            .all()
        )
        for job in jobs:
            if job.status != "succeeded":
                job.status = "succeeded"
                job.result_json = make_output(job)
                job.receipt_json = {"models": {"claude-opus-5": {}}}
                job.completed_at = datetime(2026, 9, 16, 12)
        await s.commit()
    return len(jobs)


async def job_count(sm, ws):
    async with sm() as s:
        return (
            await s.execute(
                select(func.count()).select_from(LLMJob).where(LLMJob.workspace_id == ws)
            )
        ).scalar_one()


async def test_selection_status_survives_restart_and_resume_reuses_jobs(
    editorial_sessionmaker, real_queue
):
    sm = editorial_sessionmaker
    ws = uuid.uuid4()
    async with sm() as s:
        srcs = []
        for d in range(3):
            src = await add_source(s, ws, occurred_at=datetime(2026, 9, 8 + d, 9))
            srcs.append(await add_moments(s, ws, src, 25))
    strong = str(srcs[1][0].id)

    first = await selector.select_candidates(sm, ws, WEEK)
    assert first.status == "timeout" and first.candidates == []
    n_jobs = await job_count(sm, ws)
    assert n_jobs == 3  # three 25-moment sources stay whole: one shard each
    job_status.clear()  # the process restarts: the in-process registry is gone

    async with sm() as s:
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
    assert view["state"] == "interrupted" and view["resumable"] is True
    assert view["selection_run_id"] == str(first.selection_run_id)
    assert view["job_counts"] == {"queued": 3}
    assert await rows_for(sm, ws) == []

    def output(job):
        ids = _IDS.findall(job.request_json["messages"][0]["content"])
        return {
            "candidates": [candidate_for(i, "Strong idea") for i in ids if i == strong],
            "rejections": [
                {"moment_ids": [i], "gate": "concrete_supported_substance", "reason": "thin"}
                for i in ids
                if i != strong
            ],
        }

    await finish_jobs(sm, ws, "editorial_selection", output)
    async with sm() as s:
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
    assert view["state"] == "interrupted" and "never saved" in view["current_activity"]

    resumed = await selector.select_candidates(
        sm, ws, WEEK, selection_run_id=first.selection_run_id
    )
    assert resumed.status == "complete" and resumed.resumed is True
    assert [c["moment_ids"] for c in resumed.candidates] == [[strong]]
    assert await job_count(sm, ws) == n_jobs  # no duplicate jobs
    saved = len(await rows_for(sm, ws))
    assert saved == 75

    again = await selector.select_candidates(sm, ws, WEEK, selection_run_id=first.selection_run_id)
    assert "already saved" in again.detail
    assert len(await rows_for(sm, ws)) == saved  # no duplicate proposals
    async with sm() as s:
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
        assert view["state"] == "done"
        # other tenants see nothing of this run
        assert await job_status.latest_selection_run(s, uuid.uuid4(), WEEK.isoformat()) is None


async def test_failed_shard_is_reported_and_resume_requeues_it_once(
    editorial_sessionmaker, real_queue
):
    sm = editorial_sessionmaker
    ws = uuid.uuid4()
    async with sm() as s:
        src = await add_source(s, ws, occurred_at=datetime(2026, 9, 9, 9))
        await add_moments(s, ws, src, 3)
    first = await selector.select_candidates(sm, ws, WEEK)
    async with sm() as s:
        job = (await s.execute(select(LLMJob).where(LLMJob.workspace_id == ws))).scalar_one()
        job.status, job.error_code, job.error_detail = "failed", "worker_error", "crashed"
        await s.commit()
        view = await job_status.latest_selection_run(s, ws, WEEK.isoformat())
    assert view["state"] == "failed" and view["resumable"] is True
    assert "re-queues" in view["current_activity"]

    again = await selector.select_candidates(sm, ws, WEEK, selection_run_id=first.selection_run_id)
    assert again.status == "timeout"  # re-queued, nobody leased it in the test
    async with sm() as s:
        job = (await s.execute(select(LLMJob).where(LLMJob.workspace_id == ws))).scalar_one()
        assert job.status == "queued" and job.request_json["requeue_count"] == 1
    assert await job_count(sm, ws) == 1


async def test_packet_status_survives_restart_and_resume_saves_once(
    editorial_sessionmaker, real_queue
):
    from tests.unit.test_editorial_packets import good_output, make_candidate

    sm = editorial_sessionmaker
    ws = uuid.uuid4()
    async with sm() as s:
        cand = await make_candidate(s, ws)
    out = await packets.build_packet(sm, ws, cand.id)
    assert out.status == "timeout"
    job_status.clear()

    async with sm() as s:
        view = await job_status.latest_packet_job(s, ws, cand.id)
    assert view["state"] == "interrupted" and view["resumable"] is True

    await finish_jobs(sm, ws, "recording_packet", lambda job: good_output())
    async with sm() as s:
        view = await job_status.latest_packet_job(s, ws, cand.id)
    assert view["state"] == "interrupted" and "never saved" in view["current_activity"]

    job_id = uuid.UUID(view["job_ids"][0])
    first = await packets.build_packet(sm, ws, cand.id, resume_job_id=job_id)
    second = await packets.build_packet(sm, ws, cand.id, resume_job_id=job_id)
    assert first.packet and second.packet and first.packet["id"] == second.packet["id"]
    assert await job_count(sm, ws) == 1
    async with sm() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(RecordingPacket)
                .where(RecordingPacket.workspace_id == ws)
            )
        ).scalar_one()
        view = await job_status.latest_packet_job(s, ws, cand.id)
        assert await job_status.latest_packet_job(s, uuid.uuid4(), cand.id) is None
    assert n == 1 and view["state"] == "done"


async def test_routes_report_durable_state_and_resume_after_restart(
    editorial_sessionmaker, real_queue, monkeypatch
):
    import httpx
    from fastapi import FastAPI
    from pydantic import SecretStr

    from tce.api.routers import editorial as editorial_router

    monkeypatch.setattr(settings, "private_access_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    app = FastAPI()
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    sm = editorial_sessionmaker
    ws = uuid.uuid4()
    h = {"Authorization": "Bearer synthetic-test-key", "X-Workspace-Id": str(ws)}
    async with sm() as s:
        src = await add_source(s, ws, occurred_at=datetime(2026, 9, 9, 9))
        (m,) = await add_moments(s, ws, src, 1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = (
            await c.post("/api/v1/editorial/select", json={"week_start": "2026-09-07"}, headers=h)
        ).json()
        assert first["resumed"] is False
        job_status.clear()  # restart

        st = (
            await c.get("/api/v1/editorial/select-status?week_start=2026-09-07", headers=h)
        ).json()
        assert st["job"]["state"] == "interrupted" and st["job"]["source"] == "durable"
        jobs = (await c.get("/api/v1/editorial/jobs", headers=h)).json()
        assert [j["kind"] for j in jobs["in_flight"]] == ["select"]

        await finish_jobs(
            sm,
            ws,
            "editorial_selection",
            lambda job: {"candidates": [candidate_for(m.id, "Synthetic idea")], "rejections": []},
        )
        again = (
            await c.post("/api/v1/editorial/select", json={"week_start": "2026-09-07"}, headers=h)
        ).json()
        assert again["resumed"] is True
        assert again["selection_run_id"] == first["selection_run_id"]
        st = (
            await c.get("/api/v1/editorial/select-status?week_start=2026-09-07", headers=h)
        ).json()
        assert st["job"]["state"] == "done" and st["persisted_counts"] == {"proposed": 1}
        assert await job_count(sm, ws) == 1

        other = {**h, "X-Workspace-Id": str(uuid.uuid4())}
        st = (
            await c.get("/api/v1/editorial/select-status?week_start=2026-09-07", headers=other)
        ).json()
        assert st["job"]["state"] == "idle" and st["durable"] is None

        # a fresh request after a saved run starts a new run
        third = (
            await c.post("/api/v1/editorial/select", json={"week_start": "2026-09-07"}, headers=h)
        ).json()
        assert third["resumed"] is False and third["selection_run_id"] != first["selection_run_id"]
