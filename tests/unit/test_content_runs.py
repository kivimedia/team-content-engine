"""Durable content-run coordinator contracts. Synthetic data only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tce.editorial import runs
from tce.models.content_run import ContentRun, ContentRunStage


def request(key="click-1", source_ids=None):
    return runs.ContentRunRequest(
        idempotency_key=key,
        scope_kind="sources" if source_ids else "week",
        source_ids=source_ids or [],
        window_start=datetime(2026, 9, 7, tzinfo=UTC),
        window_end=datetime(2026, 9, 14, tzinfo=UTC),
        maximum_candidate_count=12,
        target_packet_count=3,
        trigger_origin="produce_now",
    )


async def test_create_deduplicates_request_and_identical_active_scope(editorial_session):
    ws = uuid.uuid4()
    one = await runs.create_or_get_run(editorial_session, ws, request())
    await editorial_session.commit()
    same_click = await runs.create_or_get_run(editorial_session, ws, request())
    same_scope = await runs.create_or_get_run(editorial_session, ws, request("click-2"))
    assert one.id == same_click.id == same_scope.id
    stages = (
        await editorial_session.execute(
            select(ContentRunStage).where(ContentRunStage.run_id == one.id)
        )
    ).scalars().all()
    assert [stage.stage for stage in sorted(stages, key=lambda s: s.position)] == list(
        runs.STAGES
    )


async def test_targeted_and_weekly_scopes_do_not_supersede_each_other(editorial_session):
    ws = uuid.uuid4()
    weekly = await runs.create_or_get_run(editorial_session, ws, request())
    targeted = await runs.create_or_get_run(
        editorial_session, ws, request("target-1", [str(uuid.uuid4())])
    )
    assert weekly.id != targeted.id
    assert targeted.priority > weekly.priority


async def test_stage_lease_reclaims_after_crash_and_rejects_stale_completion(editorial_session):
    ws = uuid.uuid4()
    row = await runs.create_or_get_run(editorial_session, ws, request())
    await editorial_session.commit()
    now = datetime(2026, 9, 20, 10, 0)
    first = await runs.lease_next_stage(editorial_session, row.id, "owner-a", now=now)
    await editorial_session.commit()
    assert first is not None and first.stage == "collecting"
    assert await runs.lease_next_stage(editorial_session, row.id, "owner-b", now=now) is None
    later = now + timedelta(minutes=6)
    reclaimed = await runs.lease_next_stage(editorial_session, row.id, "owner-b", now=later)
    assert reclaimed is not None and reclaimed.attempt_count == 2
    assert not await runs.finish_stage(
        editorial_session, first.id, "owner-a", {"wrong": "late"}, now=later
    )
    assert await runs.finish_stage(
        editorial_session, reclaimed.id, "owner-b", {"count": 3}, now=later
    )


async def test_completed_scope_allows_a_new_run(editorial_session):
    ws = uuid.uuid4()
    one = await runs.create_or_get_run(editorial_session, ws, request())
    one.state = "ready"
    await editorial_session.commit()
    two = await runs.create_or_get_run(editorial_session, ws, request("click-later"))
    assert two.id != one.id
    assert (await editorial_session.execute(select(ContentRun))).scalars().all()
