"""A client's own login (scoped editor key) sees ONLY its workspace. Synthetic keys.

TCE_EDITOR_WORKSPACE_KEYS binds extra proxy editor keys to one workspace each.
These tests prove the owner's key, the service Bearer key and every owner request
behave exactly as before, and that a scoped key can never read or write another
workspace: not by sending X-Workspace-Id, not as a Bearer key, not through an
open legacy route, not through the LLM-job routes.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.api.deps import get_workspace_id
from tce.api.private_access import (
    ScopedEditorGuard,
    require_private_access,
    require_private_workspace,
    scoped_editor_keys,
    scoped_path_allowed,
)
from tce.settings import settings

OWNER_KEY = "owner-key-" + uuid.uuid4().hex
MATAN_KEY = "matan-key-" + uuid.uuid4().hex
ZIV_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
ZIV_WS_2 = uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793")
MATAN_WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(ZIV_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{MATAN_WS}"))


def _app() -> TestClient:
    app = FastAPI()

    @app.get("/api/v1/editorial/whoami")
    async def whoami(ws: uuid.UUID = Depends(require_private_workspace)):
        return {"ws": str(ws)}

    @app.post("/api/v1/production/write")
    async def write(ws: uuid.UUID = Depends(require_private_workspace)):
        return {"ws": str(ws)}

    @app.get("/api/v1/llm-jobs/next", dependencies=[Depends(require_private_access)])
    async def llm():
        return {"ok": True}

    @app.get("/api/v1/content")
    async def legacy(ws: uuid.UUID | None = Depends(get_workspace_id)):
        return {"ws": str(ws) if ws else None}

    @app.get("/dashboard")
    async def dashboard():
        return {"page": "dashboard"}

    @app.get("/today")
    async def today():
        return {"page": "today"}

    app.add_middleware(ScopedEditorGuard)
    return TestClient(app)


# --- The owner: exactly as before ----------------------------------------------

def test_owner_editor_key_is_bound_to_the_owner_workspace(keys):
    c = _app()
    r = c.get("/api/v1/editorial/whoami", headers={"X-TCE-Editor-Key": OWNER_KEY})
    assert r.status_code == 200 and r.json() == {"ws": str(ZIV_WS)}
    r = c.get("/api/v1/editorial/whoami",
              headers={"X-TCE-Editor-Key": OWNER_KEY, "X-Workspace-Id": str(MATAN_WS)})
    assert r.status_code == 403


def test_owner_service_bearer_still_chooses_any_workspace(keys):
    c = _app()
    for ws in (ZIV_WS, ZIV_WS_2, MATAN_WS):
        r = c.get("/api/v1/editorial/whoami",
                  headers={"Authorization": f"Bearer {OWNER_KEY}", "X-Workspace-Id": str(ws)})
        assert r.status_code == 200 and r.json() == {"ws": str(ws)}
    r = c.get("/api/v1/llm-jobs/next", headers={"Authorization": f"Bearer {OWNER_KEY}"})
    assert r.status_code == 200


def test_owner_reaches_open_legacy_routes_untouched(keys):
    c = _app()
    r = c.get("/api/v1/content", headers={"X-TCE-Editor-Key": OWNER_KEY})
    assert r.status_code == 200 and r.json() == {"ws": None}
    r = c.get("/api/v1/content",
              headers={"X-TCE-Editor-Key": OWNER_KEY, "X-Workspace-Id": str(ZIV_WS_2)})
    assert r.json() == {"ws": str(ZIV_WS_2)}
    assert c.get("/dashboard", headers={"X-TCE-Editor-Key": OWNER_KEY}).status_code == 200


def test_without_scoped_keys_configured_everything_is_as_before(keys, monkeypatch):
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(""))
    c = _app()
    r = c.get("/api/v1/editorial/whoami", headers={"X-TCE-Editor-Key": MATAN_KEY})
    assert r.status_code == 401
    assert c.get("/api/v1/content").json() == {"ws": None}


# --- Matan's key: his workspace and nothing else ---------------------------------

def test_scoped_key_reads_and_writes_only_its_workspace(keys):
    c = _app()
    h = {"X-TCE-Editor-Key": MATAN_KEY}
    assert c.get("/api/v1/editorial/whoami", headers=h).json() == {"ws": str(MATAN_WS)}
    assert c.post("/api/v1/production/write", headers=h).json() == {"ws": str(MATAN_WS)}
    same = dict(h, **{"X-Workspace-Id": str(MATAN_WS)})
    assert c.get("/api/v1/editorial/whoami", headers=same).json() == {"ws": str(MATAN_WS)}


@pytest.mark.parametrize("other", [str(ZIV_WS), str(ZIV_WS_2), "not-a-uuid", str(uuid.uuid4())])
def test_scoped_key_cannot_select_another_workspace(keys, other):
    c = _app()
    h = {"X-TCE-Editor-Key": MATAN_KEY, "X-Workspace-Id": other}
    assert c.get("/api/v1/editorial/whoami", headers=h).status_code == 403
    assert c.post("/api/v1/production/write", headers=h).status_code == 403
    assert c.get("/api/v1/content", headers=h).status_code == 403


def test_scoped_key_is_not_a_service_key(keys):
    c = _app()
    r = c.get("/api/v1/editorial/whoami",
              headers={"Authorization": f"Bearer {MATAN_KEY}", "X-Workspace-Id": str(ZIV_WS)})
    assert r.status_code == 401
    r = c.get("/api/v1/llm-jobs/next", headers={"Authorization": f"Bearer {MATAN_KEY}"})
    assert r.status_code == 401


def test_scoped_key_is_fenced_off_legacy_and_unscoped_routes(keys):
    c = _app()
    h = {"X-TCE-Editor-Key": MATAN_KEY}
    # Legacy routes read NULL-workspace owner rows: never reachable for a client.
    assert c.get("/api/v1/content", headers=h).status_code == 403
    assert c.get("/dashboard", headers=h).status_code == 403
    assert c.get("/api/v1/llm-jobs/next", headers=h).status_code == 403
    assert c.get("/today", headers=h).status_code == 200


def test_llm_dependency_refuses_a_scoped_key_even_without_the_fence(keys):
    import asyncio

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_private_access(authorization=None, x_tce_editor_key=MATAN_KEY))
    assert exc.value.status_code == 403


def test_bad_scoped_entries_are_ignored(keys, monkeypatch):
    monkeypatch.setattr(
        settings, "editor_workspace_keys",
        SecretStr(f"short:{MATAN_WS},{OWNER_KEY}:{MATAN_WS},{MATAN_KEY}:not-a-uuid,nocolon"),
    )
    assert scoped_editor_keys() == []


def test_fence_paths():
    for ok in ("/today", "/record", "/topics/abc", "/scripts/x", "/library/u/talk", "/i18n-he.js",
               "/api/v1/production/recording-queue", "/api/v1/editorial/today",
               "/api/v1/content-runs/worker"):
        assert scoped_path_allowed(ok), ok
    for no in ("/dashboard", "/api/v1/content", "/api/v1/llm-jobs/next", "/media/x.mp4",
               "/api/v1/images/a.png", "/api/v1/evidence/x", "/api/v1/news/x", "/docs",
               "/openapi.json", "/api/v1/admin/x"):
        assert not scoped_path_allowed(no), no


def test_every_real_route_the_fence_lets_through_is_workspace_scoped():
    """Walks the real app: anything a scoped key can reach must bind the workspace."""
    from tce.api.app import create_app

    app = create_app()

    def calls(dep):
        for d in dep.dependencies:
            yield d.call
            yield from calls(d)

    leaks = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        if not scoped_path_allowed(route.path):
            continue
        if route.path == "/api/v1/production/social-media/{upload_id}/{token}.mp4":
            continue  # a signed public link for the social networks, by design
        if require_private_workspace not in set(calls(route.dependant)):
            leaks.append(route.path)
    assert leaks == []
    assert any(m.cls is ScopedEditorGuard for m in app.user_middleware)
