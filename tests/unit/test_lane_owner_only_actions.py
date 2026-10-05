"""Review of feat/matan-login-rtl (5-Oct): Matan's own login opened the owner-only actions.

His scoped key reaches every /api/v1/production/ and /api/v1/editorial/ route of his
workspace. Six of those spend the OWNER's resources or voice, whatever workspace asks:

- publishing/publish runs the schedule-* skills, whose .env is Ziv's Instagram,
  Facebook, YouTube and LinkedIn: Matan's video would go out on Ziv's accounts;
- publishing/draft, /revise and the copy edit write posts with COPY_SYSTEM ("Ziv
  Raviv's walking videos", English, his post rules), and every finished edit starts
  that writer on its own (start_draft_posts);
- packets/{id}/export writes to Ziv's Google account and shares with his team;
- candidates/{id}/packet runs the owner's packet writer, which content_runs already
  refuses for a lane workspace because it puts invented first-person stories in the
  performer's mouth.

A lane workspace is refused on all six (409, before any lookup), and its finished
edits start no post writer. Owner workspaces have no lane profile, so for them
nothing changes. Synthetic keys; no database is touched by a refusal.

Merged 5-Oct (feat/matan-tce-integrated) with feat/matan-persona-voice, which gave a
lane workspace its OWN writers: its script (editorial.lane_packets, through
packets.build_packet) and its Hebrew posts (copy_system(persona)). So the script and
the post WRITING routes are allowed again and its finished edits start its own post
writer (tests/unit/test_matan_decisions_5oct.py); posting and the Google export, which
run on the owner's own accounts, stay refused here, by one guard
(private_access.refuse_lane_workspace).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.settings import settings

OWNER_KEY = "owner-key-" + uuid.uuid4().hex
MATAN_KEY = "matan-key-" + uuid.uuid4().hex
ZIV_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
ZIV_WS_2 = uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793")
MATAN_WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
ANY = str(uuid.uuid4())

OWNER_ONLY = [
    ("post", f"/api/v1/production/uploads/{ANY}/publishing/publish", {"platforms": ["instagram"]}),
    ("post", f"/api/v1/production/packets/{ANY}/export", None),
]


@pytest.fixture
def matan_login(monkeypatch):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(ZIV_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{MATAN_WS}"))
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN_WS}:performer")


@pytest.fixture
def client(matan_login):
    from tce.api.app import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.mark.parametrize(("method", "path", "body"), OWNER_ONLY)
def test_matans_login_is_refused_the_owner_only_actions(client, method, path, body):
    kwargs = {"headers": {"X-TCE-Editor-Key": MATAN_KEY}}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 409, (path, r.status_code, r.text[:300])
    assert "owner" in r.json()["detail"].lower()


@pytest.mark.parametrize(("method", "path", "body"), OWNER_ONLY)
def test_the_service_key_cannot_do_them_for_his_workspace_either(client, method, path, body):
    kwargs = {"headers": {"Authorization": f"Bearer {OWNER_KEY}", "X-Workspace-Id": str(MATAN_WS)}}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 409, (path, r.status_code, r.text[:300])


@pytest.mark.parametrize("ws", [ZIV_WS, ZIV_WS_2, None])
def test_owner_workspaces_pass_the_check_unchanged(matan_login, ws):
    from tce.api.private_access import refuse_lane_workspace

    assert refuse_lane_workspace(ws, "posting") is None


def test_the_check_names_what_was_refused(matan_login):
    from fastapi import HTTPException

    from tce.api.private_access import refuse_lane_workspace

    with pytest.raises(HTTPException) as err:
        refuse_lane_workspace(MATAN_WS, "posting")
    assert err.value.status_code == 409
    assert "posting" in err.value.detail


def test_a_finished_edit_in_his_workspace_starts_his_own_post_writer(matan_login, monkeypatch):
    # Merged 5-Oct: draft_posts writes his posts with his own writer (and nothing with
    # the owner's when his profile cannot be read): test_matan_decisions_5oct.py.
    from tce.api.routers import production

    spawned: list[object] = []

    def fake_spawn(coro):
        spawned.append(coro)
        coro.close()

    monkeypatch.setattr(production, "_spawn", fake_spawn)
    production.start_draft_posts(uuid.uuid4(), MATAN_WS)
    assert len(spawned) == 1


@pytest.mark.parametrize("ws", [ZIV_WS, ZIV_WS_2])
def test_an_owner_finished_edit_still_starts_the_post_writer(matan_login, monkeypatch, ws):
    from tce.api.routers import production

    spawned: list[object] = []

    def fake_spawn(coro):
        spawned.append(coro)
        coro.close()

    monkeypatch.setattr(production, "_spawn", fake_spawn)
    production.start_draft_posts(uuid.uuid4(), ws)
    assert len(spawned) == 1


# --- Review 5-Oct: two X-TCE-Editor-Key headers -------------------------------
# The guard read the LAST value and FastAPI's Header() reads the FIRST, so
# [his key, junk] passed the fence as "no scoped key" while the app still saw his.


def _dup_app():
    from fastapi import Depends, FastAPI

    from tce.api.deps import get_workspace_id
    from tce.api.private_access import ScopedEditorGuard

    app = FastAPI()

    @app.get("/api/v1/content")
    async def legacy(ws: uuid.UUID | None = Depends(get_workspace_id)):
        return {"ws": str(ws) if ws else None}

    app.add_middleware(ScopedEditorGuard)
    return TestClient(app)


@pytest.mark.parametrize("order", ["scoped-first", "scoped-last"])
def test_a_second_editor_key_header_cannot_slip_his_key_past_the_fence(matan_login, order):
    pair = [("X-TCE-Editor-Key", MATAN_KEY), ("X-TCE-Editor-Key", "junk-" + uuid.uuid4().hex)]
    if order == "scoped-last":
        pair.reverse()
    r = _dup_app().get("/api/v1/content", headers=pair)
    assert r.status_code == 403, (order, r.status_code, r.text)


def test_the_owner_key_alone_still_passes_the_fence(matan_login):
    r = _dup_app().get("/api/v1/content", headers={"X-TCE-Editor-Key": OWNER_KEY})
    assert r.status_code == 200
