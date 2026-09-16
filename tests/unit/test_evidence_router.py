"""Evidence router: private access and tenant isolation. Synthetic."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.api.routers import evidence as evidence_router
from tce.models.editorial import EvidenceCollectionRun, EvidenceMoment, EvidenceSource
from tce.settings import settings

KEY = "synthetic-test-key"
WS_A = uuid.uuid4()
WS_B = uuid.uuid4()


@pytest.fixture
async def seeded(editorial_sessionmaker):
    ids = {}
    async with editorial_sessionmaker() as s:
        for ws, tag in ((WS_A, "a"), (WS_B, "b")):
            src = EvidenceSource(
                workspace_id=ws, source_kind="fathom_meeting", external_id=f"m-{tag}",
                title=f"Meeting {tag}", occurred_at=datetime(2026, 9, 8), version_hash="h" * 64,
                payload_private={"turns": [{"text": f"secret words {tag}"}]}, meta={},
            )
            s.add(src)
            await s.flush()
            s.add(EvidenceMoment(
                workspace_id=ws, source_id=src.id, source_version_hash="h" * 64,
                excerpt_private="x", lesson_summary=f"lesson {tag}", claim_type="quoted",
            ))
            run = EvidenceCollectionRun(
                workspace_id=ws, source_kind="fathom_meeting",
                window_start=datetime(2026, 9, 7), window_end=datetime(2026, 9, 14),
                status="complete", counts={}, items=[], errors=[], complete=True,
                started_at=datetime(2026, 9, 15),
            )
            s.add(run)
            await s.commit()
            ids[tag] = {"source": src.id, "run": run.id}
    return ids


@pytest.fixture
def client(editorial_sessionmaker, monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", "")
    app = FastAPI()
    app.include_router(evidence_router.router, prefix="/api/v1")
    app.dependency_overrides[evidence_router.get_evidence_sessionmaker] = (
        lambda: editorial_sessionmaker
    )
    return TestClient(app)


def h(ws):
    return {"Authorization": f"Bearer {KEY}", "X-Workspace-Id": str(ws)}


async def test_no_key_401_and_unset_key_503(client, monkeypatch):
    assert client.get("/api/v1/evidence/sources").status_code == 401
    bad = {"Authorization": "Bearer wrong", "X-Workspace-Id": str(WS_A)}
    assert client.get("/api/v1/evidence/sources", headers=bad).status_code == 401
    monkeypatch.setattr(settings, "private_access_key", SecretStr(""))
    assert client.get("/api/v1/evidence/sources", headers=h(WS_A)).status_code == 503


async def test_tenant_isolation(client, seeded):
    listing = client.get("/api/v1/evidence/sources", headers=h(WS_A)).json()["sources"]
    assert [s["external_id"] for s in listing] == ["m-a"]
    assert "payload_private" not in listing[0]

    own = client.get(f"/api/v1/evidence/sources/{seeded['a']['source']}", headers=h(WS_A))
    assert own.status_code == 200 and "payload_private" in own.json()
    other = client.get(f"/api/v1/evidence/sources/{seeded['b']['source']}", headers=h(WS_A))
    assert other.status_code == 404

    moments = client.get("/api/v1/evidence/moments", headers=h(WS_A)).json()["moments"]
    assert [m["lesson_summary"] for m in moments] == ["lesson a"]

    runs = client.get("/api/v1/evidence/runs", headers=h(WS_A)).json()["runs"]
    assert [r["id"] for r in runs] == [str(seeded["a"]["run"])]
    assert client.get(
        f"/api/v1/evidence/runs/{seeded['b']['run']}", headers=h(WS_A)
    ).status_code == 404

    cov = client.get(
        "/api/v1/evidence/coverage",
        params={"window_start": "2026-09-07T00:00:00Z", "window_end": "2026-09-14T00:00:00Z"},
        headers=h(WS_A),
    ).json()
    assert cov["coverage"]["fathom_meeting"]["id"] == str(seeded["a"]["run"])


async def test_collect_returns_run_ids_and_runs_in_background(client, monkeypatch):
    called = []

    async def fake_collect(sessionmaker, ws, start, end, *, run_id=None, client=None):
        called.append((ws, run_id))
        return run_id

    monkeypatch.setattr(evidence_router.collect_mod, "collect_fathom", fake_collect)
    monkeypatch.setattr(evidence_router.collect_mod, "collect_github", fake_collect)
    resp = client.post(
        "/api/v1/evidence/collect",
        json={"kinds": ["fathom", "github"], "window_start": "2026-09-07T00:00:00Z",
              "window_end": "2026-09-14T00:00:00Z"},
        headers=h(WS_A),
    )
    assert resp.status_code == 200
    run_ids = resp.json()["run_ids"]
    assert len(run_ids) == 2
    assert {str(r) for _, r in called} == set(run_ids)
    assert all(ws == WS_A for ws, _ in called)

    bad = client.post(
        "/api/v1/evidence/collect",
        json={"kinds": ["slack"], "window_start": "2026-09-07T00:00:00Z",
              "window_end": "2026-09-14T00:00:00Z"},
        headers=h(WS_A),
    )
    assert bad.status_code == 422
