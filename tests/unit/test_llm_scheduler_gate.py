"""The scheduler cannot be started (or its jobs triggered) over HTTP unless enabled."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tce.api.routers import scheduler as scheduler_router
from tce.settings import settings


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(scheduler_router.router, prefix="/api/v1")
    return app


async def test_start_and_trigger_refused_when_disabled(monkeypatch):
    started = []
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(scheduler_router.scheduler, "start", lambda: started.append(1))

    async def fake_trigger(name):
        started.append(name)
        return {}

    monkeypatch.setattr(scheduler_router.scheduler, "trigger_job", fake_trigger)
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/scheduler/start")
        assert r.status_code == 409 and "TCE_SCHEDULER_ENABLED" in r.json()["detail"]
        r = await c.post("/api/v1/scheduler/trigger/daily_content")
        assert r.status_code == 409
        status = await c.get("/api/v1/scheduler/status")
        assert status.status_code == 200 and status.json()["enabled"] is False
    assert started == []


async def test_start_allowed_when_enabled(monkeypatch):
    started = []
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(scheduler_router.scheduler, "start", lambda: started.append(1))
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/scheduler/start")
    assert r.status_code == 200 and started == [1]
