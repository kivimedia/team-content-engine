"""HTTP contract for /api/v1/llm-jobs (synthetic data, in-process ASGI, SQLite)."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api.routers import llm_jobs
from tce.db.session import get_db
from tce.llm import POLICY_MODEL, queue
from tce.llm.provider import LLMRequest
from tce.settings import settings
from tests.editorial_db import create_tables

KEY = "synthetic-test-key"
AUTH = {"Authorization": f"Bearer {KEY}"}
RECEIPT = {
    "models": {POLICY_MODEL: {"input_tokens": 4, "output_tokens": 2}},
    "api_key_source": "none",
    "api_provider": "firstParty",
    "auth_method": "claude.ai",
}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(llm_jobs, "_status_path", lambda: tmp_path / "worker-status.json")
    llm_jobs._worker_status.clear()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'router.sqlite'}", poolclass=NullPool
    )
    await create_tables(engine)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        yield c
    llm_jobs._worker_status.clear()
    await engine.dispose()


async def _enqueue(client, text="synthetic"):
    async with client.maker() as s:
        job = await queue.enqueue(
            s,
            LLMRequest(job_type="t", agent_name="a", messages=[{"role": "user", "content": text}]),
        )
        await s.commit()
        return job


async def test_requires_private_key(client):
    assert (await client.get("/api/v1/llm-jobs/")).status_code == 401
    assert (await client.post("/api/v1/llm-jobs/lease", json={"worker_id": "w"})).status_code == 401


async def test_not_configured_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(""))
    assert (await client.get("/api/v1/llm-jobs/", headers=AUTH)).status_code == 503


async def test_lease_heartbeat_complete_flow(client):
    job = await _enqueue(client)
    r = await client.post("/api/v1/llm-jobs/lease", json={"worker_id": "w1"}, headers=AUTH)
    assert r.status_code == 200
    leased = r.json()["job"]
    assert leased["id"] == str(job.id) and leased["policy_model"] == POLICY_MODEL
    assert leased["request_json"]["messages"][0]["content"] == "synthetic"
    attempt = leased["attempt_id"]

    empty = await client.post("/api/v1/llm-jobs/lease", json={"worker_id": "w2"}, headers=AUTH)
    assert empty.json() == {"job": None}

    hb = await client.post(
        f"/api/v1/llm-jobs/{job.id}/heartbeat", json={"attempt_id": attempt}, headers=AUTH
    )
    assert hb.status_code == 200 and hb.json()["leased_until"]

    body = {"attempt_id": attempt, "result_text": "ok", "result_json": None, "receipt": RECEIPT}
    done = await client.post(f"/api/v1/llm-jobs/{job.id}/complete", json=body, headers=AUTH)
    assert done.status_code == 200 and done.json()["status"] == "succeeded"
    repeat = await client.post(f"/api/v1/llm-jobs/{job.id}/complete", json=body, headers=AUTH)
    assert repeat.status_code == 200 and repeat.json()["status"] == "succeeded"

    listing = await client.get("/api/v1/llm-jobs/?limit=10", headers=AUTH)
    assert listing.json()["counts"] == {"succeeded": 1}
    one = await client.get(f"/api/v1/llm-jobs/{job.id}", headers=AUTH)
    assert one.json()["result_text"] == "ok"


async def test_stale_attempt_is_409(client):
    job = await _enqueue(client)
    r = await client.post("/api/v1/llm-jobs/lease", json={"worker_id": "w1"}, headers=AUTH)
    old_attempt = r.json()["job"]["attempt_id"]
    # Simulate the lease expiring (worker crash) and another worker reclaiming it.
    async with client.maker() as s:
        later = queue.utcnow() + timedelta(hours=2)
        reclaimed = await queue.lease_job(s, "w2", 600, now=later)
        await s.commit()
        assert reclaimed is not None
    body = {"attempt_id": old_attempt, "result_text": "late", "receipt": RECEIPT}
    stale = await client.post(f"/api/v1/llm-jobs/{job.id}/complete", json=body, headers=AUTH)
    assert stale.status_code == 409
    hb = await client.post(
        f"/api/v1/llm-jobs/{job.id}/heartbeat", json={"attempt_id": old_attempt}, headers=AUTH
    )
    assert hb.status_code == 409


async def test_fail_capacity_route(client):
    job = await _enqueue(client)
    leased = (
        await client.post("/api/v1/llm-jobs/lease", json={"worker_id": "w1"}, headers=AUTH)
    ).json()["job"]
    r = await client.post(
        f"/api/v1/llm-jobs/{job.id}/fail",
        json={
            "attempt_id": leased["attempt_id"],
            "error_code": "capacity",
            "error_detail": "usage limit reached",
            "retry_at": "2099-01-01T00:00:00Z",
        },
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "waiting_capacity"
    assert r.json()["retry_at"].startswith("2099-01-01T00:00:00")
    again = await client.post("/api/v1/llm-jobs/lease", json={"worker_id": "w2"}, headers=AUTH)
    assert again.json() == {"job": None}


async def test_unknown_job_404(client):
    r = await client.get("/api/v1/llm-jobs/00000000-0000-0000-0000-000000000000", headers=AUTH)
    assert r.status_code == 404


async def test_worker_status_drops_unknown_fields(client):
    payload = {
        "worker_id": "w1",
        "ok": True,
        "auth_method": "claude.ai",
        "subscription_type": "max",
        "email": "someone@example.com",
        "orgId": "org-1",
        "token": "secret",
    }
    r = await client.post("/api/v1/llm-jobs/worker-status", json=payload, headers=AUTH)
    assert r.status_code == 200
    got = (await client.get("/api/v1/llm-jobs/worker-status", headers=AUTH)).json()
    latest = got["latest"]
    assert latest["worker_id"] == "w1" and latest["auth_method"] == "claude.ai"
    assert "email" not in latest and "orgId" not in latest and "token" not in latest
