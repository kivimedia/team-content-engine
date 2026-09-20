from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from tce.api.routers import content_runs as api
from tce.models.content_run import EditorialSchedule
from tce.models.editorial import EvidenceSource
from tce.settings import settings

KEY = "content-run-test-key"


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")

    async def no_coordinate(*_args, **_kwargs):
        return None

    monkeypatch.setattr(api, "coordinate_content_run", no_coordinate)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_content_sessionmaker] = lambda: editorial_sessionmaker
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


def auth(workspace_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(workspace_id)}


async def test_create_deduplicates_request_and_scope(client):
    workspace_id = uuid.uuid4()
    body = {
        "idempotency_key": "click-1",
        "scope_kind": "week",
        "window_start": "2026-09-07T00:00:00Z",
        "window_end": "2026-09-14T00:00:00Z",
    }
    first = await client.post(
        "/api/v1/content-runs/produce-now", json=body, headers=auth(workspace_id)
    )
    second = await client.post("/api/v1/content-runs", json=body, headers=auth(workspace_id))
    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert [item["stage"] for item in first.json()["stages"]] == list(api.runs.STAGES)


async def test_claude_request_requires_choice_for_ambiguous_meetings(
    client, editorial_sessionmaker
):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        for suffix in ("morning", "afternoon"):
            db.add(
                EvidenceSource(
                    workspace_id=workspace_id,
                    source_kind="fathom_meeting",
                    external_id=f"dovid-{suffix}",
                    title=f"Dovid {suffix}",
                    occurred_at=datetime.now(UTC).replace(tzinfo=None),
                    version_hash=uuid.uuid4().hex,
                    revision=1,
                    fetch_status="ok",
                    payload_private={"turns": []},
                )
            )
        await db.commit()
    response = await client.post(
        "/api/v1/content-runs/from-claude/request",
        json={"text": "The Fathom with Dovid is sick. Make a script", "idempotency_key": "c1"},
        headers=auth(workspace_id),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "needs_source_choice"
    assert len(response.json()["choices"]) == 2


def test_due_occurrence_uses_israel_timezone_and_marks_catchup():
    schedule = EditorialSchedule(
        workspace_id=uuid.uuid4(),
        name="weekly-content",
        enabled=True,
        timezone="Asia/Jerusalem",
        weekday=0,
        local_time="07:00",
        catchup_days=7,
    )
    due = api.due_occurrence(schedule, datetime(2026, 9, 21, 6, 0, tzinfo=UTC))
    assert due is not None
    key, instant, late = due
    assert key.startswith("2026-09-21T07:00")
    assert instant == datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    assert late is True


async def test_schedule_tick_is_durable_and_duplicate_safe(editorial_sessionmaker):
    workspace_id = uuid.uuid4()
    async with editorial_sessionmaker() as db:
        db.add(
            EditorialSchedule(
                workspace_id=workspace_id,
                name="weekly-content",
                enabled=True,
                timezone="Asia/Jerusalem",
                weekday=0,
                local_time="07:00",
                catchup_days=7,
            )
        )
        await db.commit()
    instant = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    first = await api.tick_due_schedules(
        editorial_sessionmaker, workspace_id=workspace_id, now=instant
    )
    second = await api.tick_due_schedules(
        editorial_sessionmaker, workspace_id=workspace_id, now=instant
    )
    assert first[0]["status"] == "queued"
    assert second[0] == {
        "status": "already_created",
        "schedule": "weekly-content",
        "occurrence_key": "2026-09-21T07:00+0300",
        "workspace_id": str(workspace_id),
        "run_id": first[0]["run_id"],
    }
