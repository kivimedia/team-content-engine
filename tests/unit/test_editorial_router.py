"""/editorial router: private access, tenant isolation, background jobs and status."""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

import tce.llm
from tce.api.routers import editorial as editorial_router
from tce.editorial import status as job_status
from tce.llm import LLMResult
from tce.models.editorial import REJECTION_GATES, EvidenceMoment, EvidenceSource, TopicCandidate
from tce.settings import settings

KEY = "synthetic-test-key"


@pytest.fixture
async def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    job_status.clear()
    app = FastAPI()
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: (
        editorial_sessionmaker
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    job_status.clear()


def headers(ws) -> dict:
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def add_candidate(sm, ws, title="Synthetic idea", status="proposed"):
    async with sm() as s:
        c = TopicCandidate(
            workspace_id=ws,
            week_start=datetime(2026, 9, 7),
            moment_ids=[],
            title=title,
            lesson="l",
            audience="coaches",
            public_angle="a",
            gates={},
            status=status,
            rank=1,
        )
        s.add(c)
        await s.commit()
        return c


async def test_requires_key(client):
    r = await client.get(
        "/api/v1/editorial/candidates", headers={"X-Workspace-Id": str(uuid.uuid4())}
    )
    assert r.status_code == 401


async def test_unconfigured_key_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(""))
    r = await client.get("/api/v1/editorial/candidates", headers=headers(uuid.uuid4()))
    assert r.status_code == 503


async def test_tenant_isolation(client, editorial_sessionmaker):
    ws_a, ws_b = uuid.uuid4(), uuid.uuid4()
    a = await add_candidate(editorial_sessionmaker, ws_a, "A idea")
    await add_candidate(editorial_sessionmaker, ws_b, "B idea")

    r = await client.get(
        "/api/v1/editorial/candidates?week_start=2026-09-07", headers=headers(ws_b)
    )
    assert [c["title"] for c in r.json()["candidates"]] == ["B idea"]

    cid = str(a.id)
    for method, path, body in (
        ("GET", f"/api/v1/editorial/candidates/{cid}", None),
        ("PATCH", f"/api/v1/editorial/candidates/{cid}", {"status": "selected"}),
        ("POST", f"/api/v1/editorial/candidates/{cid}/feedback", {"kind": "approve"}),
        ("GET", f"/api/v1/editorial/candidates/{cid}/feedback", None),
        ("POST", f"/api/v1/editorial/candidates/{cid}/packet", None),
        ("GET", f"/api/v1/editorial/candidates/{cid}/packets", None),
        ("GET", f"/api/v1/editorial/candidates/{cid}/packet-status", None),
        ("GET", f"/api/v1/editorial/packets/{uuid.uuid4()}", None),
    ):
        resp = await client.request(method, path, json=body, headers=headers(ws_b))
        assert resp.status_code == 404, (method, path, resp.status_code)

    # owner still sees it unchanged
    r = await client.get(f"/api/v1/editorial/candidates/{cid}", headers=headers(ws_a))
    assert r.status_code == 200 and r.json()["status"] == "proposed" and r.json()["feedback"] == []


async def test_feedback_and_patch_roundtrip(client, editorial_sessionmaker):
    ws = uuid.uuid4()
    c = await add_candidate(editorial_sessionmaker, ws)
    base = f"/api/v1/editorial/candidates/{c.id}"
    r = await client.post(
        f"{base}/feedback",
        json={"kind": "angle", "rating": "change_angle", "note": "lead with the question"},
        headers=headers(ws),
    )
    assert r.status_code == 200 and r.json()["preference_version"] == 1
    bad = await client.post(f"{base}/feedback", json={"kind": "gate_reject"}, headers=headers(ws))
    assert bad.status_code == 400
    r = await client.patch(
        base, json={"status": "selected", "editor_notes": "record first"}, headers=headers(ws)
    )
    assert r.json()["status"] == "selected" and len(r.json()["feedback"]) == 1
    assert (
        await client.patch(base, json={"status": "bogus"}, headers=headers(ws))
    ).status_code == 400


async def test_select_runs_in_background_and_reports_status(
    client, editorial_sessionmaker, monkeypatch
):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        src = EvidenceSource(
            workspace_id=ws,
            source_kind="fathom_meeting",
            external_id="m1",
            occurred_at=datetime(2026, 9, 8),
            version_hash="a" * 64,
            payload_private={},
        )
        s.add(src)
        await s.flush()
        m = EvidenceMoment(
            workspace_id=ws,
            source_id=src.id,
            source_version_hash="a" * 64,
            speaker_confidence="high",
            excerpt_private="synthetic",
            lesson_summary="synthetic lesson",
            claim_type="paraphrased",
            sensitivity_flags=[],
        )
        s.add(m)
        await s.commit()
    job_id = uuid.uuid4()

    async def fake_complete(req, *, wait_timeout_s=None):
        return LLMResult(
            job_id=job_id,
            text="",
            model="claude-opus-5",
            structured={
                "candidates": [
                    {
                        "moment_ids": [str(m.id)],
                        "title": "Synthetic idea",
                        "lesson": "l",
                        "audience": "coaches",
                        "public_angle": "a",
                        "gates": {g: {"pass": True, "reason": "r"} for g in REJECTION_GATES},
                    }
                ],
                "rejections": [],
            },
        )

    monkeypatch.setattr(tce.llm, "complete", fake_complete)
    r = await client.post(
        "/api/v1/editorial/select", json={"week_start": "2026-09-07"}, headers=headers(ws)
    )
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert (
        await client.post(
            "/api/v1/editorial/select",
            json={"week_start": "2026-09-07", "max_candidates": 9},
            headers=headers(ws),
        )
    ).status_code == 422

    st = (
        await client.get(
            "/api/v1/editorial/select-status?week_start=2026-09-07", headers=headers(ws)
        )
    ).json()
    assert st["job"]["state"] == "done"
    assert str(job_id) in st["job"]["job_ids"]
    assert st["persisted_counts"] == {"proposed": 1}

    other = (
        await client.get(
            "/api/v1/editorial/select-status?week_start=2026-09-07", headers=headers(uuid.uuid4())
        )
    ).json()
    assert other["job"]["state"] == "idle" and other["persisted_counts"] == {}

    cands = (
        await client.get("/api/v1/editorial/candidates?week_start=2026-09-07", headers=headers(ws))
    ).json()["candidates"]
    assert [c["title"] for c in cands] == ["Synthetic idea"]
    assert cands[0]["citations_private"][0]["moment_id"] == str(m.id)


async def test_strategy_route_reports_provenance(client):
    r = await client.get("/api/v1/editorial/strategy", headers=headers(uuid.uuid4()))
    body = r.json()
    assert r.status_code == 200 and "strategy session" in body["text"].lower()
    kinds = {s["kind"] for s in body["sources"]}
    assert {"file", "prompt_version"} <= kinds
