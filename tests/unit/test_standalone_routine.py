"""A client-local weekly routine runs once and follows daylight saving time."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tce.db.base import Base
from tce.standalone import routine, workflow
from tce.standalone.app import ClientConfig
from tce.standalone.jobs import queue_job
from tce.standalone.models import (
    StandaloneAccount,
    StandaloneConfigRevision,
    StandaloneMembership,
    StandaloneRoutineRun,
    StandaloneWorkspace,
)


def test_routine_uses_client_timezone_across_daylight_saving():
    scheduled = {"enabled": True, "weekday": 0, "local_time": "09:00"}
    assert routine.due_local_date(
        datetime(2026, 10, 12, 13, 30, tzinfo=UTC), "America/New_York", scheduled
    ).isoformat() == "2026-10-12"
    assert routine.due_local_date(
        datetime(2026, 11, 2, 14, 30, tzinfo=UTC), "America/New_York", scheduled
    ).isoformat() == "2026-11-02"
    assert routine.due_local_date(
        datetime(2026, 10, 12, 22, 30, tzinfo=UTC), "America/New_York", scheduled
    ).isoformat() == "2026-10-12"
    assert routine.due_local_date(
        datetime(2026, 10, 11, 13, 30, tzinfo=UTC), "America/New_York", scheduled
    ) is None
    assert routine.due_local_date(
        datetime(2026, 10, 12, 12, 30, tzinfo=UTC), "America/New_York", scheduled
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["anthropic_api", "claude_code"])
async def test_weekly_scheduler_has_one_receipt_and_does_not_repeat(monkeypatch, mode):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all,
            tables=[
                table
                for table in Base.metadata.tables.values()
                if table.name.startswith("standalone_")
            ],
        )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(routine, "async_session", sessionmaker)
    workspace_id = uuid.uuid4()
    account_id = uuid.uuid4()
    async with sessionmaker() as db:
        db.add_all(
            [
                StandaloneWorkspace(
                    id=workspace_id, name="Synthetic", slug="synthetic", timezone="America/New_York"
                ),
                StandaloneAccount(
                    id=account_id,
                    email="routine@example.test",
                    password_hash="synthetic-test-only",
                    email_verified_at=datetime.now(UTC),
                ),
            ]
        )
        await db.flush()
        db.add(StandaloneMembership(workspace_id=workspace_id, account_id=account_id, role="owner"))
        config = ClientConfig(
            display_name="Synthetic",
            timezone="America/New_York",
            source_lanes=[
                {"name": str(i), "kind": "upload", "enabled": i == 0} for i in range(3)
            ],
            brain_mode=mode,
            routine={"enabled": True, "weekday": 0, "local_time": "09:00"},
        )
        db.add(
            StandaloneConfigRevision(
                workspace_id=workspace_id,
                revision=1,
                content=config.model_dump(),
                actor_id=account_id,
                reason="settings",
            )
        )
        await db.commit()
    calls = []

    async def fake_scout(principal, db):
        calls.append(principal.workspace_id)
        if mode == "claude_code":
            job = await queue_job(
                db, principal.workspace_id, "scout", {"prompt": "Synthetic weekly scout"}
            )
            return JSONResponse(status_code=202, content={"job_id": str(job.id)})
        return {"ideas": [], "sources_considered": 0}

    monkeypatch.setattr(workflow, "scout", fake_scout)
    due = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)
    await routine.tick(due)
    await routine.tick(due)
    async with sessionmaker() as db:
        rows = (await db.execute(select(StandaloneRoutineRun))).scalars().all()
    assert calls == [workspace_id]
    assert len(rows) == 1
    assert rows[0].status == ("queued" if mode == "claude_code" else "done")
    assert (rows[0].job_id is not None) == (mode == "claude_code")
    assert rows[0].routine_date.isoformat() == "2026-10-12"
    await engine.dispose()
