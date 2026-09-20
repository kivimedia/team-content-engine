"""Phase 3: durable VPS cron ownership of content-run schedules.

Every test here is synthetic: no worker, no provider, no network. The worker
presence receipt is monkeypatched (offline by default) and capacity comes from
a seeded `WorkerGroupState` row, exactly the two durable facts production uses.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api.routers import content_runs as api
from tce.api.routers import llm_jobs
from tce.editorial import runs
from tce.llm import queue as llm_queue
from tce.models.content_run import (
    ContentRun,
    EditorialSchedule,
    EditorialScheduleOccurrence,
    WorkerGroupState,
)
from tce.settings import settings
from tests.editorial_db import create_tables

KEY = "schedule-test-key"
IL = ZoneInfo("Asia/Jerusalem")


def _schedule(
    workspace_id: uuid.UUID,
    name: str = "weekly-content",
    *,
    cadence: str = "weekly",
    weekday: int = 0,
    local_time: str = "07:30",
    catchup_days: int = 7,
    final_stage: str = "exporting",
    window_days: int = 7,
    enabled: bool = True,
) -> EditorialSchedule:
    return EditorialSchedule(
        workspace_id=workspace_id,
        name=name,
        enabled=enabled,
        cadence=cadence,
        timezone="Asia/Jerusalem",
        weekday=weekday,
        local_time=local_time,
        catchup_days=catchup_days,
        final_stage=final_stage,
        window_days=window_days,
    )


def _offline() -> dict:
    return {"workers": [], "latest": None}


def _online() -> dict:
    worker = {
        "worker_id": "pc-1",
        "state": "idle",
        "stale": False,
        "age_seconds": 4,
        "received_at": datetime.now(UTC).isoformat(),
    }
    return {"workers": [worker], "latest": worker}


@pytest.fixture(autouse=True)
def worker_offline(monkeypatch):
    """Never read the real worker-status file; tests flip presence explicitly."""

    async def status() -> dict:
        return _offline()

    monkeypatch.setattr(llm_jobs, "get_worker_status", status)


def set_worker(monkeypatch, online: bool) -> None:
    async def status() -> dict:
        return _online() if online else _offline()

    monkeypatch.setattr(llm_jobs, "get_worker_status", status)


@pytest.fixture
async def file_sessionmaker(tmp_path):
    """File-backed SQLite so concurrent ticks and a restart use real separate
    connections; the shared in-memory engine cannot serve either."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'schedule.sqlite'}", poolclass=NullPool
    )
    await create_tables(engine)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    dispatched: list[uuid.UUID] = []

    async def record_coordinate(_sm, _ws, run_id):
        dispatched.append(run_id)

    monkeypatch.setattr(api, "coordinate_content_run", record_coordinate)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_content_sessionmaker] = lambda: editorial_sessionmaker
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        value.dispatched = dispatched  # type: ignore[attr-defined]
        yield value


def auth(workspace_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(workspace_id)}


async def _counts(sm, workspace_id: uuid.UUID) -> tuple[int, int]:
    async with sm() as db:
        occurrences = (
            await db.execute(
                select(func.count())
                .select_from(EditorialScheduleOccurrence)
                .where(EditorialScheduleOccurrence.workspace_id == workspace_id)
            )
        ).scalar_one()
        content_runs = (
            await db.execute(
                select(func.count())
                .select_from(ContentRun)
                .where(ContentRun.workspace_id == workspace_id)
            )
        ).scalar_one()
    return occurrences, content_runs


# ---------------------------------------------------------------------------
# due_occurrence: Israel DST, catch-up, keys
# ---------------------------------------------------------------------------


def test_daily_key_carries_summer_offset():
    schedule = _schedule(uuid.uuid4(), "daily-evidence", cadence="daily", local_time="07:15")
    due = api.due_occurrence(schedule, datetime(2026, 9, 21, 4, 20, tzinfo=UTC))
    assert due is not None
    key, instant, late = due
    assert key == "2026-09-21T07:15+0300"
    assert instant == datetime(2026, 9, 21, 4, 15, tzinfo=UTC)
    assert late is False


def test_daily_across_israel_dst_end_switches_to_plus_0200():
    # Israel DST ends Sunday 25-Oct-2026 02:00 (clocks go back to 01:00).
    schedule = _schedule(uuid.uuid4(), "daily-evidence", cadence="daily", local_time="07:15")
    before = api.due_occurrence(schedule, datetime(2026, 10, 24, 4, 20, tzinfo=UTC))
    after = api.due_occurrence(schedule, datetime(2026, 10, 25, 5, 20, tzinfo=UTC))
    assert before is not None and after is not None
    assert before[0] == "2026-10-24T07:15+0300"
    assert before[1] == datetime(2026, 10, 24, 4, 15, tzinfo=UTC)
    assert after[0] == "2026-10-25T07:15+0200"
    assert after[1] == datetime(2026, 10, 25, 5, 15, tzinfo=UTC)
    # Same wall-clock intent, different UTC moments, different durable keys.
    assert before[1] + timedelta(hours=25) == after[1]
    # At 04:20Z on the 25th the local time is 06:20 (+0200): not yet due today,
    # so yesterday's occurrence is the candidate, not a phantom +0300 one.
    early = api.due_occurrence(schedule, datetime(2026, 10, 25, 4, 20, tzinfo=UTC))
    assert early is not None and early[0] == "2026-10-24T07:15+0300"


def test_daily_across_israel_dst_start_switches_to_plus_0300():
    # Israel DST starts Friday 27-Mar-2026 02:00 (clocks jump to 03:00).
    schedule = _schedule(uuid.uuid4(), "daily-evidence", cadence="daily", local_time="07:15")
    before = api.due_occurrence(schedule, datetime(2026, 3, 26, 5, 20, tzinfo=UTC))
    after = api.due_occurrence(schedule, datetime(2026, 3, 27, 4, 20, tzinfo=UTC))
    assert before is not None and after is not None
    assert before[0] == "2026-03-26T07:15+0200"
    assert before[1] == datetime(2026, 3, 26, 5, 15, tzinfo=UTC)
    assert after[0] == "2026-03-27T07:15+0300"
    assert after[1] == datetime(2026, 3, 27, 4, 15, tzinfo=UTC)
    assert before[1] + timedelta(hours=23) == after[1]


def test_weekly_across_dst_end_keeps_monday_wall_clock():
    schedule = _schedule(uuid.uuid4(), weekday=0, local_time="07:30")
    summer = api.due_occurrence(schedule, datetime(2026, 10, 19, 4, 35, tzinfo=UTC))
    winter = api.due_occurrence(schedule, datetime(2026, 10, 26, 5, 35, tzinfo=UTC))
    assert summer is not None and winter is not None
    assert summer[0] == "2026-10-19T07:30+0300"
    assert summer[1] == datetime(2026, 10, 19, 4, 30, tzinfo=UTC)
    assert winter[0] == "2026-10-26T07:30+0200"
    assert winter[1] == datetime(2026, 10, 26, 5, 30, tzinfo=UTC)
    assert summer[2] is False and winter[2] is False


def test_missed_execution_within_catchup_is_late_not_lost():
    weekly = _schedule(uuid.uuid4(), weekday=0, local_time="07:30", catchup_days=7)
    # Thursday: the box was down since Monday morning.
    due = api.due_occurrence(weekly, datetime(2026, 9, 24, 10, 0, tzinfo=UTC))
    assert due is not None
    assert due[0] == "2026-09-21T07:30+0300"
    assert due[2] is True
    daily = _schedule(uuid.uuid4(), "daily-evidence", cadence="daily", local_time="07:15")
    due = api.due_occurrence(daily, datetime(2026, 9, 24, 10, 0, tzinfo=UTC))
    assert due is not None
    assert due[0] == "2026-09-24T07:15+0300"
    assert due[2] is True


def test_weekly_before_this_weeks_moment_offers_last_week_within_catchup():
    weekly = _schedule(uuid.uuid4(), weekday=0, local_time="07:30", catchup_days=7)
    # Monday 07:00 local: this week's 07:30 has not happened; last Monday is
    # six days and 23.5 hours old, still inside the seven-day catch-up.
    due = api.due_occurrence(weekly, datetime(2026, 9, 28, 4, 0, tzinfo=UTC))
    assert due is not None
    assert due[0] == "2026-09-21T07:30+0300"
    assert due[2] is True
    # One minute after 07:30 the fresh occurrence takes over.
    due = api.due_occurrence(weekly, datetime(2026, 9, 28, 4, 31, tzinfo=UTC))
    assert due is not None
    assert due[0] == "2026-09-28T07:30+0300"
    assert due[2] is False


def test_no_catch_up_beyond_the_window():
    weekly = _schedule(uuid.uuid4(), weekday=0, local_time="07:30", catchup_days=2)
    assert api.due_occurrence(weekly, datetime(2026, 9, 24, 10, 0, tzinfo=UTC)) is None
    weekly.catchup_days = 7
    # Eight days after the last Monday moment nothing older is offered.
    weekly.enabled = True
    due = api.due_occurrence(weekly, datetime(2026, 9, 29, 10, 0, tzinfo=UTC))
    assert due is not None and due[0] == "2026-09-28T07:30+0300"


async def test_tick_after_long_outage_creates_one_occurrence_not_a_backlog(
    editorial_sessionmaker,
):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        db.add(
            _schedule(
                workspace_id,
                "daily-evidence",
                cadence="daily",
                local_time="07:15",
                final_stage="extracting",
            )
        )
        await db.commit()
    # Ten days of no ticks, then one.
    results = await api.tick_due_schedules(
        editorial_sessionmaker,
        workspace_id=workspace_id,
        now=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )
    assert [r["status"] for r in results] == ["queued"]
    assert results[0]["occurrence_key"] == "2026-10-01T07:15+0300"
    assert results[0]["late"] is True
    assert await _counts(editorial_sessionmaker, workspace_id) == (1, 1)


# ---------------------------------------------------------------------------
# occurrence windows
# ---------------------------------------------------------------------------


def test_weekly_window_is_the_completed_local_week():
    schedule = _schedule(uuid.uuid4(), weekday=0, local_time="07:30")
    key, due_utc, _ = api.due_occurrence(schedule, datetime(2026, 9, 21, 4, 35, tzinfo=UTC))
    start, end = api.occurrence_window(schedule, due_utc)
    assert key == "2026-09-21T07:30+0300"
    assert end == datetime(2026, 9, 20, 21, 0, tzinfo=UTC)  # Monday 00:00 IL
    assert start == datetime(2026, 9, 13, 21, 0, tzinfo=UTC)  # previous Monday 00:00 IL


def test_daily_window_ends_at_the_occurrence_and_spans_window_days():
    schedule = _schedule(
        uuid.uuid4(), "daily-evidence", cadence="daily", local_time="07:15", window_days=7
    )
    _, due_utc, _ = api.due_occurrence(schedule, datetime(2026, 9, 21, 4, 20, tzinfo=UTC))
    start, end = api.occurrence_window(schedule, due_utc)
    assert end == datetime(2026, 9, 21, 4, 15, tzinfo=UTC)
    assert start == datetime(2026, 9, 14, 4, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
# durability: repeated, concurrent, restarted ticks
# ---------------------------------------------------------------------------


async def test_repeated_ticks_create_exactly_one_occurrence(editorial_sessionmaker):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        db.add(_schedule(workspace_id))
        await db.commit()
    instant = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    outcomes = []
    for offset in (0, 0, 5, 60):
        outcomes.append(
            await api.tick_due_schedules(
                editorial_sessionmaker,
                workspace_id=workspace_id,
                now=instant + timedelta(minutes=offset),
            )
        )
    assert [o[0]["status"] for o in outcomes] == ["queued"] + ["already_created"] * 3
    run_ids = {o[0]["run_id"] for o in outcomes}
    assert len(run_ids) == 1
    assert all(o[0]["occurrence_key"] == "2026-09-21T07:30+0300" for o in outcomes)
    assert await _counts(editorial_sessionmaker, workspace_id) == (1, 1)


async def test_concurrent_ticks_share_one_occurrence(file_sessionmaker):
    workspace_id = uuid.uuid4()
    async with file_sessionmaker() as db:
        db.add(_schedule(workspace_id))
        db.add(
            _schedule(
                workspace_id,
                "daily-evidence",
                cadence="daily",
                local_time="07:15",
                final_stage="extracting",
            )
        )
        await db.commit()
    instant = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    outcomes = await asyncio.gather(
        *[
            api.tick_due_schedules(file_sessionmaker, workspace_id=workspace_id, now=instant)
            for _ in range(4)
        ]
    )
    flat = [r for results in outcomes for r in results]
    by_schedule: dict[str, list[dict]] = {}
    for item in flat:
        by_schedule.setdefault(item["schedule"], []).append(item)
    assert set(by_schedule) == {"weekly-content", "daily-evidence"}
    for name, items in by_schedule.items():
        statuses = sorted(i["status"] for i in items)
        assert statuses == ["already_created"] * 3 + ["queued"], (name, statuses)
        assert len({i["run_id"] for i in items}) == 1, (name, items)
    assert await _counts(file_sessionmaker, workspace_id) == (2, 2)


async def test_restart_with_a_new_sessionmaker_sees_the_same_occurrence(tmp_path):
    path = tmp_path / "restart.sqlite"
    workspace_id = uuid.uuid4()
    instant = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    await create_tables(engine)
    first_sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with first_sm() as db:
        db.add(_schedule(workspace_id))
        await db.commit()
    first = await api.tick_due_schedules(first_sm, workspace_id=workspace_id, now=instant)
    await engine.dispose()  # the process died

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    second_sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        second = await api.tick_due_schedules(
            second_sm, workspace_id=workspace_id, now=instant + timedelta(minutes=10)
        )
        assert first[0]["status"] == "queued"
        assert second[0]["status"] == "already_created"
        assert second[0]["run_id"] == first[0]["run_id"]
        assert await _counts(second_sm, workspace_id) == (1, 1)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# worker truth: waiting_worker and waiting_capacity
# ---------------------------------------------------------------------------


def _collect_only(monkeypatch):
    """Run the real stage executor except for collecting, which needs no worker
    and would otherwise call the Fathom and GitHub collectors."""
    real = api._execute_stage

    async def execute(sm, run, stage):
        if stage == "collecting":
            return {"collection": "synthetic"}
        return await real(sm, run, stage)

    monkeypatch.setattr(api, "_execute_stage", execute)


async def test_run_says_waiting_worker_when_no_worker_has_reported(
    editorial_sessionmaker, monkeypatch
):
    _collect_only(monkeypatch)
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        run = await runs.create_or_get_run(
            db,
            workspace_id,
            runs.ContentRunRequest(
                idempotency_key="daily-1",
                scope_kind="week",
                window_start=datetime(2026, 9, 14, tzinfo=UTC),
                window_end=datetime(2026, 9, 21, tzinfo=UTC),
                trigger_origin="daily_schedule",
                final_stage="extracting",
            ),
        )
        await db.commit()
        run_id = run.id
    before = runs.utcnow()
    await api.coordinate_content_run(editorial_sessionmaker, workspace_id, run_id)
    async with editorial_sessionmaker() as db:
        row = await runs.get_run(db, workspace_id, run_id)
        stages = await runs.list_stages(db, run_id)
    assert row.state == "waiting_worker"
    assert row.current_stage == "extracting"
    assert "No subscription worker has reported" in (row.error_detail or "")
    by_stage = {s.stage: s for s in stages}
    assert by_stage["collecting"].status == "succeeded"
    assert by_stage["extracting"].status == "waiting_worker"
    retry = by_stage["extracting"].next_eligible_at
    assert retry is not None
    assert before + timedelta(minutes=4) <= retry <= before + timedelta(minutes=6)


async def test_run_says_waiting_capacity_with_the_groups_retry_at(
    editorial_sessionmaker, monkeypatch
):
    _collect_only(monkeypatch)
    set_worker(monkeypatch, online=True)
    workspace_id = uuid.uuid4()
    retry_at = (runs.utcnow() + timedelta(hours=2)).replace(microsecond=0)
    async with editorial_sessionmaker() as db:
        db.add(
            WorkerGroupState(
                group_key=llm_queue.WORKER_GROUP_KEY,
                state="waiting_capacity",
                retry_at=retry_at,
                reason="weekly limit reached",
            )
        )
        run = await runs.create_or_get_run(
            db,
            workspace_id,
            runs.ContentRunRequest(
                idempotency_key="daily-2",
                scope_kind="week",
                window_start=datetime(2026, 9, 14, tzinfo=UTC),
                window_end=datetime(2026, 9, 21, tzinfo=UTC),
                trigger_origin="daily_schedule",
                final_stage="extracting",
            ),
        )
        await db.commit()
        run_id = run.id
    state = await api.worker_availability(editorial_sessionmaker)
    assert state["online"] is True
    assert state["capped"] is True
    assert state["retry_at"] == retry_at
    assert "weekly limit reached" in state["detail"]
    await api.coordinate_content_run(editorial_sessionmaker, workspace_id, run_id)
    async with editorial_sessionmaker() as db:
        row = await runs.get_run(db, workspace_id, run_id)
        stages = {s.stage: s for s in await runs.list_stages(db, run_id)}
        # A future retry_at keeps the run off the re-drive list.
        assert await runs.list_redrivable_runs(db, workspace_id) == []
    assert row.state == "waiting_capacity"
    assert stages["extracting"].next_eligible_at == retry_at
    assert "weekly limit reached" in (row.error_detail or "")


async def test_worker_availability_is_online_when_a_fresh_receipt_exists(
    editorial_sessionmaker, monkeypatch
):
    assert (await api.worker_availability(editorial_sessionmaker))["online"] is False
    set_worker(monkeypatch, online=True)
    state = await api.worker_availability(editorial_sessionmaker)
    assert state["online"] is True
    assert state["online_count"] == 1
    assert state["capped"] is False
    assert state["capacity"]["state"] == "available"
    assert state["detail"] == "1 worker(s) online"


# ---------------------------------------------------------------------------
# the daily evidence run
# ---------------------------------------------------------------------------


async def test_daily_evidence_run_has_two_stages_and_reaches_ready(
    editorial_sessionmaker, monkeypatch
):
    executed: list[str] = []

    async def execute(_sm, _run, stage):
        executed.append(stage)
        return {"stage": stage}

    monkeypatch.setattr(api, "_execute_stage", execute)
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        db.add(
            _schedule(
                workspace_id,
                "daily-evidence",
                cadence="daily",
                local_time="07:15",
                final_stage="extracting",
            )
        )
        await db.commit()
    results = await api.tick_due_schedules(
        editorial_sessionmaker,
        workspace_id=workspace_id,
        now=datetime(2026, 9, 21, 4, 20, tzinfo=UTC),
    )
    assert results[0]["status"] == "queued"
    assert results[0]["final_stage"] == "extracting"
    assert results[0]["window_start"] == "2026-09-14T04:15:00+00:00"
    assert results[0]["window_end"] == "2026-09-21T04:15:00+00:00"
    run_id = uuid.UUID(results[0]["run_id"])
    async with editorial_sessionmaker() as db:
        row = await runs.get_run(db, workspace_id, run_id)
        stages = await runs.list_stages(db, run_id)
    assert row.trigger_origin == "daily_schedule"
    assert row.final_stage == "extracting"
    assert [s.stage for s in stages] == ["collecting", "extracting"]
    await api.coordinate_content_run(editorial_sessionmaker, workspace_id, run_id)
    async with editorial_sessionmaker() as db:
        row = await runs.get_run(db, workspace_id, run_id)
    assert executed == ["collecting", "extracting"]
    assert row.state == "ready"
    assert row.current_stage == "ready"
    assert row.ready_at is not None


async def test_weekly_run_keeps_all_six_stages(editorial_sessionmaker):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        db.add(_schedule(workspace_id))
        await db.commit()
    results = await api.tick_due_schedules(
        editorial_sessionmaker,
        workspace_id=workspace_id,
        now=datetime(2026, 9, 21, 4, 35, tzinfo=UTC),
    )
    run_id = uuid.UUID(results[0]["run_id"])
    async with editorial_sessionmaker() as db:
        row = await runs.get_run(db, workspace_id, run_id)
        stages = await runs.list_stages(db, run_id)
    assert row.trigger_origin == "weekly_schedule"
    assert row.final_stage == "exporting"
    assert [s.stage for s in stages] == list(runs.STAGES)
    assert results[0]["window_start"] == "2026-09-13T21:00:00+00:00"
    assert results[0]["window_end"] == "2026-09-20T21:00:00+00:00"


def test_final_stage_changes_the_scope_hash():
    base = dict(
        idempotency_key="k",
        scope_kind="week",
        window_start=datetime(2026, 9, 14, tzinfo=UTC),
        window_end=datetime(2026, 9, 21, tzinfo=UTC),
    )
    full_payload, full = runs.normalized_scope(runs.ContentRunRequest(**base))
    evidence_only = runs.normalized_scope(runs.ContentRunRequest(**base, final_stage="extracting"))[
        1
    ]
    assert full != evidence_only
    # A full run hashes exactly as it did before final_stage existed, so the
    # weekly occurrence attaches to an active pre-041 Produce-now run for the
    # same window instead of creating a twin.
    assert "final_stage" not in full_payload
    pre_041 = {
        "scope_kind": "week",
        "source_ids": [],
        "window_start": "2026-09-14T00:00:00",
        "window_end": "2026-09-21T00:00:00",
        "maximum_candidate_count": 6,
        "target_packet_count": 3,
    }
    assert full_payload == pre_041
    with pytest.raises(ValueError):
        runs.stages_through("publishing")


async def test_scheduled_full_week_attaches_to_the_active_produce_now_run(
    editorial_sessionmaker,
):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        produce_now = await runs.create_or_get_run(
            db,
            workspace_id,
            runs.ContentRunRequest(
                idempotency_key="produce-now:2026-09-14T11",
                scope_kind="week",
                window_start=datetime(2026, 9, 6, 21, tzinfo=UTC),
                window_end=datetime(2026, 9, 13, 21, tzinfo=UTC),
                trigger_origin="produce_now",
            ),
        )
        db.add(_schedule(workspace_id))
        await db.commit()
        produce_now_id = produce_now.id
    # Sunday 20-Sep 15:30 IL: the candidate is Monday 14-Sep 07:30, late.
    results = await api.tick_due_schedules(
        editorial_sessionmaker,
        workspace_id=workspace_id,
        now=datetime(2026, 9, 20, 12, 30, tzinfo=UTC),
    )
    assert results[0]["occurrence_key"] == "2026-09-14T07:30+0300"
    assert results[0]["status"] == "queued"
    assert results[0]["run_id"] == str(produce_now_id)
    assert await _counts(editorial_sessionmaker, workspace_id) == (1, 1)


# ---------------------------------------------------------------------------
# the HTTP surface the cron and the runbook use
# ---------------------------------------------------------------------------


async def test_schedule_api_configures_lists_and_ticks_both_schedules(client, monkeypatch):
    workspace_id = uuid.uuid4()
    weekly = await client.put(
        "/api/v1/content-runs/schedule/weekly-content",
        json={
            "enabled": True,
            "cadence": "weekly",
            "weekday": 0,
            "local_time": "07:30",
            "final_stage": "exporting",
            "window_days": 7,
            "catchup_days": 7,
        },
        headers=auth(workspace_id),
    )
    daily = await client.put(
        "/api/v1/content-runs/schedule/daily-evidence",
        json={
            "enabled": True,
            "cadence": "daily",
            "local_time": "07:15",
            "final_stage": "extracting",
            "window_days": 7,
        },
        headers=auth(workspace_id),
    )
    assert weekly.status_code == 200 and daily.status_code == 200
    assert weekly.json()["cadence"] == "weekly"
    assert daily.json()["cadence"] == "daily"
    assert daily.json()["final_stage"] == "extracting"
    unknown = await client.put(
        "/api/v1/content-runs/schedule/hourly-nonsense",
        json={"enabled": True},
        headers=auth(workspace_id),
    )
    assert unknown.status_code == 404

    listing = await client.get("/api/v1/content-runs/schedule", headers=auth(workspace_id))
    assert listing.status_code == 200
    names = [row["name"] for row in listing.json()["schedules"]]
    assert names == ["daily-evidence", "weekly-content"]
    assert listing.json()["worker"]["online"] is False
    assert "No subscription worker" in listing.json()["worker"]["detail"]

    first = await client.post("/api/v1/content-runs/schedule/tick", headers=auth(workspace_id))
    second = await client.post("/api/v1/content-runs/schedule/tick", headers=auth(workspace_id))
    assert first.status_code == 200 and second.status_code == 200
    body = first.json()
    assert body["worker"]["online"] is False
    assert set(body["worker"]) == {"online", "online_count", "capacity", "detail"}
    queued = [o for o in body["occurrences"] if o["status"] == "queued"]
    # Both schedules are due at any real "now" (catch-up covers the week).
    assert {o["schedule"] for o in queued} == {"weekly-content", "daily-evidence"}
    assert body["status"] == "queued"
    queued_ids = {uuid.UUID(o["run_id"]) for o in queued}
    assert set(client.dispatched[:2]) == queued_ids
    again = second.json()
    assert all(o["status"] == "already_created" for o in again["occurrences"])
    assert {o["run_id"] for o in again["occurrences"]} == {o["run_id"] for o in queued}
    # The stub coordinator never leased a stage, which is what a coordinator
    # that died before leasing looks like: the next tick re-drives, creates
    # nothing, and says so.
    assert again["status"] == "redriven"
    assert {r["run_id"] for r in again["redriven"]} == {str(i) for i in queued_ids}
    assert all(r["state"] == "queued" and r["stage"] == "collecting" for r in again["redriven"])
    assert len(client.dispatched) == 4


async def test_tick_redrives_waiting_runs_only_when_a_worker_is_online(
    client, editorial_sessionmaker, monkeypatch
):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        run = await runs.create_or_get_run(
            db,
            workspace_id,
            runs.ContentRunRequest(
                idempotency_key="parked",
                scope_kind="week",
                window_start=datetime(2026, 9, 14, tzinfo=UTC),
                window_end=datetime(2026, 9, 21, tzinfo=UTC),
                final_stage="extracting",
            ),
        )
        await db.flush()
        stages = await runs.list_stages(db, run.id)
        stages[0].status = "succeeded"
        stages[1].status = "waiting_worker"
        stages[1].next_eligible_at = runs.utcnow() - timedelta(minutes=1)
        run.state = "waiting_worker"
        run.current_stage = "extracting"
        await db.commit()
        run_id = run.id
    offline = await client.post("/api/v1/content-runs/schedule/tick", headers=auth(workspace_id))
    assert offline.status_code == 200
    assert offline.json()["status"] == "disabled_or_not_due"
    assert offline.json()["redriven"] == []
    assert client.dispatched == []

    set_worker(monkeypatch, online=True)
    online = await client.post("/api/v1/content-runs/schedule/tick", headers=auth(workspace_id))
    assert online.json()["status"] == "redriven"
    assert online.json()["redriven"] == [
        {"run_id": str(run_id), "state": "waiting_worker", "stage": "extracting"}
    ]
    assert online.json()["worker"]["online"] is True
    assert client.dispatched == [run_id]


# ---------------------------------------------------------------------------
# lease heartbeat: a slow stage is not re-leased by the next tick
# ---------------------------------------------------------------------------


async def _leased_run(sm, workspace_id: uuid.UUID, owner: str, lease_for: timedelta):
    async with sm() as db:
        run = await runs.create_or_get_run(
            db,
            workspace_id,
            runs.ContentRunRequest(
                idempotency_key=f"slow-{owner}",
                scope_kind="week",
                window_start=datetime(2026, 9, 14, tzinfo=UTC),
                window_end=datetime(2026, 9, 21, tzinfo=UTC),
                final_stage="extracting",
            ),
        )
        await db.flush()
        stage = await runs.lease_next_stage(db, run.id, owner, lease_for=lease_for)
        await db.commit()
        return run, stage, stage.leased_until


async def test_slow_stage_keeps_its_lease_and_finishes(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(api, "LEASE_HEARTBEAT", timedelta(milliseconds=40))

    async def slow(_sm, _run, stage):
        await asyncio.sleep(0.25)
        return {"stage": stage}

    monkeypatch.setattr(api, "_execute_stage", slow)
    workspace_id = uuid.uuid4()
    owner = "api:slow"
    run, stage, first_until = await _leased_run(
        editorial_sessionmaker, workspace_id, owner, timedelta(milliseconds=100)
    )
    output = await api._execute_stage_leased(editorial_sessionmaker, run, stage, owner)
    assert output == {"stage": "collecting"}
    async with editorial_sessionmaker() as db:
        row = await db.get(type(stage), stage.id)
        assert row.lease_owner == owner
        assert row.leased_until > first_until + timedelta(milliseconds=150)
        # The renewed lease is what the next tick sees: still held, not re-drivable.
        assert await runs.list_redrivable_runs(db, workspace_id) == []
        assert await runs.finish_stage(db, stage.id, owner, output)
        await db.commit()


async def test_re_leased_stage_makes_the_first_coordinator_stand_down(
    editorial_sessionmaker, monkeypatch
):
    monkeypatch.setattr(api, "LEASE_HEARTBEAT", timedelta(milliseconds=40))
    cancelled = asyncio.Event()

    async def never_finishes(_sm, _run, _stage):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {}

    monkeypatch.setattr(api, "_execute_stage", never_finishes)
    workspace_id = uuid.uuid4()
    run, stage, _ = await _leased_run(
        editorial_sessionmaker, workspace_id, "api:first", timedelta(milliseconds=30)
    )
    await asyncio.sleep(0.05)  # the lease lapses, a tick re-leases it
    async with editorial_sessionmaker() as db:
        taken = await runs.lease_next_stage(db, run.id, "api:second")
        await db.commit()
    assert taken is not None and taken.lease_owner == "api:second"
    with pytest.raises(runs.LeaseLostError):
        await api._execute_stage_leased(editorial_sessionmaker, run, stage, "api:first")
    assert cancelled.is_set()
    async with editorial_sessionmaker() as db:
        assert not await runs.finish_stage(db, stage.id, "api:first", {})
        row = await db.get(type(stage), stage.id)
        assert row.lease_owner == "api:second" and row.status == "running"


# ---------------------------------------------------------------------------
# drafting: a rejected finalist is skipped, not fatal
# ---------------------------------------------------------------------------


async def _drafting_run(sm, workspace_id: uuid.UUID, ranked: list[str], target: int = 2):
    async with sm() as db:
        run = await runs.create_or_get_run(
            db,
            workspace_id,
            runs.ContentRunRequest(
                idempotency_key=f"draft-{uuid.uuid4()}",
                scope_kind="week",
                window_start=datetime(2026, 9, 14, tzinfo=UTC),
                window_end=datetime(2026, 9, 21, tzinfo=UTC),
                target_packet_count=target,
            ),
        )
        await db.flush()
        for stage in await runs.list_stages(db, run.id):
            if stage.stage == "ranking":
                stage.status = "succeeded"
                stage.output_refs = {"candidate_ids": ranked, "ranked": len(ranked)}
            elif stage.stage in {"collecting", "extracting", "selecting"}:
                stage.status = "succeeded"
        await db.commit()
        return run


def _outcome(packet_id: str | None, detail: str = ""):
    from types import SimpleNamespace

    return SimpleNamespace(
        status="ok" if packet_id else "failed",
        packet={"id": packet_id} if packet_id else None,
        job_id=uuid.uuid4(),
        detail=detail,
        errors=[detail] if detail else [],
        retry_at=None,
    )


async def test_drafting_skips_a_rejected_finalist_and_uses_the_spare(
    editorial_sessionmaker, monkeypatch
):
    ranked = [str(uuid.uuid4()) for _ in range(4)]
    seen: list[str] = []

    async def build(_sm, _ws, candidate_id):
        cid = str(candidate_id)
        seen.append(cid)
        # The first finalist's packet cites evidence outside the idea.
        if cid == ranked[0]:
            return _outcome(None, "packet hook cited evidence outside the selected idea")
        return _outcome(f"packet-for-{cid[:8]}")

    monkeypatch.setattr("tce.editorial.packets.build_packet", build)
    set_worker(monkeypatch, online=True)
    workspace_id = uuid.uuid4()
    run = await _drafting_run(editorial_sessionmaker, workspace_id, ranked, target=2)
    output = await api._execute_stage(editorial_sessionmaker, run, "drafting")
    assert len(output["packet_ids"]) == 2
    assert [r["candidate_id"] for r in output["rejected"]] == [ranked[0]]
    assert "outside the selected idea" in output["rejected"][0]["detail"]
    # Stops as soon as the target is met: the fourth spare is never built.
    assert seen == ranked[:3]


async def test_drafting_fails_only_when_no_finalist_produces_a_packet(
    editorial_sessionmaker, monkeypatch
):
    ranked = [str(uuid.uuid4()) for _ in range(3)]

    async def build(_sm, _ws, candidate_id):
        return _outcome(None, "packet failed validation")

    monkeypatch.setattr("tce.editorial.packets.build_packet", build)
    set_worker(monkeypatch, online=True)
    workspace_id = uuid.uuid4()
    run = await _drafting_run(editorial_sessionmaker, workspace_id, ranked)
    with pytest.raises(ValueError, match=r"no finalist produced a packet \(3 rejected\)"):
        await api._execute_stage(editorial_sessionmaker, run, "drafting")
