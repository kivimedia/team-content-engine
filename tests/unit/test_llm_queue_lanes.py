"""Lease lanes and the lease wake (synthetic, SQLite).

23-Nov-2026: a conversation, an edit request or a rewrite he asked for sat behind a
batch of research jobs, because leases went strictly oldest first. A job a person is
waiting on now leases ahead of batch work. The lane changes ORDER only.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select, update

from tce.llm import queue
from tce.llm.provider import LLMRequest
from tce.models.content_run import WorkerGroupState
from tce.models.llm_job import LLMJob

T0 = datetime(2026, 11, 23, 8, 0, 0)
BATCH = "evidence_moments"
TALK = "editorial_conversation"


def req(job_type: str, n: int) -> LLMRequest:
    return LLMRequest(
        job_type=job_type,
        agent_name="tester",
        messages=[{"role": "user", "content": f"synthetic {job_type} {n}"}],
    )


async def add(session, job_type: str, n: int, at: datetime) -> LLMJob:
    """Enqueue one job with an exact created_at, so the oldest-first order is known."""
    job = await queue.enqueue(session, req(job_type, n))
    await session.commit()
    await session.execute(update(LLMJob).where(LLMJob.id == job.id).values(created_at=at))
    await session.commit()
    return job


async def lease_ids(session, count: int) -> list:
    out = []
    for i in range(count):
        job = await queue.lease_job(session, f"w{i}", 600)
        await session.commit()
        out.append(job.id if job else None)
    return out


async def test_an_interactive_job_queued_after_ten_batch_jobs_is_leased_first(editorial_session):
    batch = [await add(editorial_session, BATCH, i, T0 + timedelta(seconds=i)) for i in range(10)]
    talk = await add(editorial_session, TALK, 0, T0 + timedelta(minutes=5))
    got = await lease_ids(editorial_session, 12)
    assert got[0] == talk.id, "the conversation must not wait behind ten research jobs"
    assert got[1:11] == [j.id for j in batch], "the batch keeps its oldest-first order"
    assert got[11] is None


async def test_each_lane_keeps_todays_oldest_first_order(editorial_session):
    s = editorial_session
    unknown = await add(s, "a_type_added_later", 0, T0)  # unknown type: batch
    batch_b = await add(s, "editorial_selection", 0, T0 + timedelta(seconds=1))
    old_agent = await add(s, "agent.weekly_planner", 0, T0 + timedelta(seconds=2))
    edit = await add(s, "video_edit_request", 0, T0 + timedelta(seconds=3))
    news = await add(s, "news_appraisal", 0, T0 + timedelta(seconds=4))
    copy = await add(s, "video_post_copy", 0, T0 + timedelta(seconds=5))
    script = await add(s, "recording_packet", 0, T0 + timedelta(seconds=6))
    got = await lease_ids(s, 8)
    assert got == [
        edit.id,
        copy.id,
        script.id,
        unknown.id,
        batch_b.id,
        old_agent.id,
        news.id,
        None,
    ]


async def test_same_created_at_falls_back_to_id_as_before(editorial_session):
    s = editorial_session
    a = await add(s, TALK, 1, T0)
    b = await add(s, TALK, 2, T0)
    x = await add(s, BATCH, 1, T0)
    y = await add(s, BATCH, 2, T0)
    got = await lease_ids(s, 4)
    assert got == sorted([a.id, b.id], key=str) + sorted([x.id, y.id], key=str)


async def test_a_leased_batch_job_is_never_taken_for_an_interactive_one(editorial_session):
    s = editorial_session
    running = await add(s, BATCH, 0, T0)
    leased = await queue.lease_job(s, "busy-worker", 600)
    await s.commit()
    attempt = leased.attempt_id
    talk = await add(s, TALK, 0, T0 + timedelta(seconds=1))

    second = await queue.lease_job(s, "idle-worker", 600)
    await s.commit()
    assert second.id == talk.id
    assert await queue.lease_job(s, "third-worker", 600) is None

    row = await queue.get_job(s, running.id)
    assert row.status == "leased" and row.lease_owner == "busy-worker"
    assert row.attempt_id == attempt and row.attempt_count == 1
    beat = await queue.heartbeat(s, running.id, attempt, 600)
    assert beat.lease_owner == "busy-worker"


async def test_a_parked_interactive_job_waits_for_its_retry_time_as_before(editorial_session):
    s = editorial_session
    talk = await add(s, TALK, 0, T0)
    batch = await add(s, BATCH, 0, T0 + timedelta(seconds=1))
    leased = await queue.lease_job(s, "w1", 600)
    assert leased.id == talk.id
    retry_at = queue.utcnow() + timedelta(hours=1)
    parked = await queue.fail_job(
        s, talk.id, leased.attempt_id, error_code="capacity", retry_at=retry_at
    )
    await s.commit()
    assert parked.status == "waiting_capacity" and parked.attempt_count == 0

    # The shared group is paused: nothing is leased, in either lane.
    assert await queue.lease_job(s, "w2", 600) is None
    # An operator lifts the pause by hand; the parked job still waits for its time.
    group = (await s.execute(select(WorkerGroupState))).scalar_one()
    group.state = "available"
    group.retry_at = None
    await s.commit()
    nxt = await queue.lease_job(s, "w2", 600)
    await s.commit()
    assert nxt.id == batch.id, "a parked job is not leasable before its retry time"
    later = retry_at + timedelta(seconds=1)
    back = await queue.lease_job(s, "w3", 600, now=later)
    await s.commit()
    assert back.id == talk.id and back.attempt_count == 1


async def test_a_retrying_interactive_job_keeps_its_attempts(editorial_session):
    s = editorial_session
    talk = await add(s, TALK, 0, T0)
    await add(s, BATCH, 0, T0 - timedelta(hours=1))
    for attempt in (1, 2, 3):
        job = await queue.lease_job(s, "w", 600)
        assert job.id == talk.id and job.attempt_count == attempt
        out = await queue.fail_job(s, job.id, job.attempt_id, error_code="timeout")
        await s.commit()
        assert out.status == ("queued" if attempt < 3 else "failed")
    nxt = await queue.lease_job(s, "w", 600)
    assert nxt is not None and nxt.job_type == BATCH


async def test_a_requeued_failed_interactive_job_still_requeues_only_once(editorial_session):
    s = editorial_session
    await add(s, BATCH, 0, T0 - timedelta(hours=1))
    talk = await add(s, TALK, 0, T0)
    await s.execute(
        update(LLMJob).where(LLMJob.id == talk.id).values(status="failed", error_code="timeout")
    )
    await s.commit()
    from tce.llm import LLMUnavailable

    with pytest.raises(LLMUnavailable):
        await queue.enqueue(s, req(TALK, 0))
    again = await queue.enqueue(s, req(TALK, 0), requeue_failed=True)
    await s.commit()
    assert again.id == talk.id and again.status == "queued"
    leased = await queue.lease_job(s, "w", 600)
    assert leased.id == talk.id and leased.attempt_count == 1
    await queue.fail_job(s, leased.id, leased.attempt_id, error_code="auth")
    await s.commit()
    with pytest.raises(LLMUnavailable):
        await queue.enqueue(s, req(TALK, 0), requeue_failed=True)


async def test_the_lease_query_sorts_by_lane_first(editorial_sessionmaker):
    """The candidate SELECT itself carries the lane: one statement, no second pass."""
    seen: list[str] = []
    async with editorial_sessionmaker() as s:
        await add(s, TALK, 0, T0)
        engine = s.bind
        listener = lambda *a: seen.append(a[2])  # noqa: E731 - (conn, cursor, statement, ...)
        event.listen(engine.sync_engine, "before_cursor_execute", listener)
        try:
            await queue.lease_job(s, "w", 600)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", listener)
    picks = [sql for sql in seen if "FROM llm_jobs" in sql and "ORDER BY" in sql]
    assert picks, seen
    order = picks[0].split("ORDER BY", 1)[1]
    assert order.strip().upper().startswith("CASE WHEN")
    assert order.index("created_at") > order.upper().index("CASE")


def test_the_postgres_lease_still_skips_locked_rows():
    from sqlalchemy.dialects import postgresql

    stmt = (
        select(LLMJob)
        .where(queue._leasable_clause(queue.utcnow()))
        .order_by(queue._lane_order(), LLMJob.created_at, LLMJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ORDER BY CASE WHEN" in sql and "FOR UPDATE SKIP LOCKED" in sql


# --- every job type in the code has a lane ----------------------------------------

# Batch on purpose: research and scheduled work a person does not sit and wait for.
KNOWN_BATCH = {
    "evidence_moments": "the evidence pass over a week of calls and commits",
    "editorial_selection": "the weekly sharded selection (a spoken idea's scoped run shares it)",
    "news_appraisal": "the daily run's appraisals, up to ten a day per workspace",
}


def _job_type_constants() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2] / "src" / "tce"
    found: dict[str, str] = {}
    pattern = re.compile(r'^[A-Z_]*(?:JOB_TYPE|_JOB)\s*=\s*"([a-z0-9_.]+)"', re.M)
    for path in root.rglob("*.py"):
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            found[name] = str(path.relative_to(root))
    return found


def test_every_job_type_constant_has_a_decided_lane():
    found = _job_type_constants()
    assert len(found) >= 15, f"the scan found too few job types to be trusted: {found}"
    undecided = {
        name: where
        for name, where in found.items()
        if name not in queue.INTERACTIVE_JOB_TYPES and name not in KNOWN_BATCH
    }
    assert not undecided, (
        "a new job type needs a lane: add it to queue.INTERACTIVE_JOB_TYPES if a "
        f"person waits on it, else to KNOWN_BATCH here: {undecided}"
    )
    stale = queue.INTERACTIVE_JOB_TYPES - set(found)
    assert not stale, f"interactive types no code writes any more: {stale}"


def test_the_named_writers_are_in_the_interactive_lane():
    from tce.editorial import conversation, hook_scripts, packets, script_check
    from tce.production import autoedit, publishing, qc
    from tce.production import rules as rule_text
    from tce.production.creatorz import reels

    for job_type in (
        conversation.JOB_TYPE,
        packets.JOB_TYPE,
        packets.VOICE_PASS_JOB_TYPE,
        packets.MORE_HOOKS_JOB_TYPE,
        hook_scripts.JOB_TYPE,
        script_check.JOB_TYPE,
        autoedit.EDIT_REQUEST_JOB,
        autoedit.EDIT_BATCH_JOB,
        autoedit.REVIEW_JOB,
        qc.ASIDES_JOB,
        reels.MOMENTS_JOB,
        publishing.COPY_JOB,
        publishing.REVISE_JOB,
        rule_text.DISTILL_JOB,
    ):
        assert queue.job_lane(job_type) == "interactive", job_type
    for job_type in (*KNOWN_BATCH, "agent.story_strategist", "legacy.x", None, ""):
        assert queue.job_lane(job_type) == "batch", job_type


# --- the lease wake ------------------------------------------------------------------


async def test_a_commit_that_queued_a_job_wakes_held_leases(editorial_session):
    waiter = queue.add_lease_waiter(8)
    try:
        await queue.enqueue(editorial_session, req(TALK, 1))
        await asyncio.sleep(0)
        assert not waiter.is_set(), "the row is not visible to another session before commit"
        await editorial_session.commit()
        await asyncio.sleep(0)
        assert waiter.is_set()

        waiter.clear()
        await queue.enqueue(editorial_session, req(TALK, 1))  # same job: nothing new
        await editorial_session.commit()
        await asyncio.sleep(0)
        assert not waiter.is_set()
    finally:
        queue.remove_lease_waiter(waiter)
    assert queue.held_lease_count() == 0


async def test_a_savepoint_inside_a_longer_transaction_does_not_wake_early(editorial_session):
    waiter = queue.add_lease_waiter(8)
    try:
        await queue.enqueue(editorial_session, req(TALK, 1))
        await queue.enqueue(editorial_session, req(TALK, 2))  # releases its own savepoint
        await asyncio.sleep(0)
        assert not waiter.is_set()
        await editorial_session.commit()
        await asyncio.sleep(0)
        assert waiter.is_set()
    finally:
        queue.remove_lease_waiter(waiter)


async def test_a_rolled_back_enqueue_wakes_nobody(editorial_session):
    waiter = queue.add_lease_waiter(8)
    try:
        await queue.enqueue(editorial_session, req(TALK, 1))
        await editorial_session.rollback()
        await editorial_session.commit()
        await asyncio.sleep(0)
        assert not waiter.is_set()
    finally:
        queue.remove_lease_waiter(waiter)


async def test_the_wake_registry_is_bounded():
    held = [queue.add_lease_waiter(2), queue.add_lease_waiter(2)]
    try:
        assert all(held) and queue.held_lease_count() == 2
        assert queue.add_lease_waiter(2) is None
    finally:
        for waiter in held:
            queue.remove_lease_waiter(waiter)
    assert queue.held_lease_count() == 0
