"""The hook library (T-25210): ten proved hooks, favorites, weekly picks placed on the
video they fit, and the owner-only API."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tce.hooks import catalog, library
from tce.settings import settings

WS = uuid.UUID("00000000-0000-4000-8000-000000000025")
WEEK = "2026-11-23"


def _lineup(*videos, filmed=()):
    return {
        "primary": [
            {"candidate_id": cid, "title": title, "big_idea": "", "reason": "", "filmed": cid in filmed}
            for cid, title in videos
        ],
        "reserve": [],
    }


LINEUP = _lineup(
    ("a" * 8, "Should I go ahead is not a decision"),
    ("b" * 8, "Some clients rebook at 80%"),
    ("c" * 8, "When your agent says it is done, it is not done"),
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def test_ten_proved_hooks_each_with_its_preview_clip():
    assert len(catalog.HOOKS) == 10
    assert len({h.id for h in catalog.HOOKS}) == 10
    for hook in catalog.HOOKS:
        assert hook.preview.is_file(), hook.id
        assert hook.preview.stat().st_size > 50_000, hook.id
        with hook.preview.open("rb") as handle:
            assert b"ftyp" in handle.read(32), hook.id
        for text in (hook.name, hook.what, hook.record, hook.fit_reason):
            assert "—" not in text and "--" not in text, hook.id


def test_a_pick_goes_on_the_video_it_fits_and_says_why():
    hook = catalog.BY_ID["big-number"]
    chosen, why = library.place(hook, library.week_videos(LINEUP), set())
    assert chosen == "b" * 8
    assert "\u201c80%\u201d" in why and "number" in why


def test_a_hook_with_no_rule_goes_on_a_video_with_no_hook_yet():
    hook = catalog.BY_ID["whip-in"]
    chosen, why = library.place(hook, library.week_videos(LINEUP), {"a" * 8})
    assert chosen == "b" * 8
    assert "had no hook yet" in why


def test_no_videos_this_week_places_nothing_and_says_so():
    chosen, why = library.place(catalog.BY_ID["whip-in"], [], set())
    assert chosen is None and "Choose topics" in why


def test_filmed_videos_take_no_hook():
    lineup = _lineup(("a" * 8, "One"), ("b" * 8, "Two"), filmed=("a" * 8,))
    assert [v["candidate_id"] for v in library.week_videos(lineup)] == ["b" * 8]


def test_favorites_come_first_and_survive_a_reread(store):
    run(library.toggle_favorite(WS, "proof-pop", True))
    data = run(library.library(WS, WEEK, LINEUP, lambda i: f"hooks/{i}/preview"))
    assert data["hooks"][0]["id"] == "proof-pop" and data["hooks"][0]["favorite"] is True
    assert data["favorites"] == 1
    run(library.toggle_favorite(WS, "proof-pop", False))
    data = run(library.library(WS, WEEK, LINEUP, lambda i: i))
    assert data["favorites"] == 0 and data["hooks"][0]["id"] == catalog.HOOKS[0].id


def test_pick_move_and_unpick(store):
    entry = run(library.pick(WS, WEEK, "proof-pop", LINEUP))
    assert entry["candidate_id"] == "c" * 8 and entry["chosen_by"] == "tce"
    moved = run(library.pick(WS, WEEK, "proof-pop", LINEUP, "a" * 8))
    assert moved["candidate_id"] == "a" * 8 and moved["chosen_by"] == "owner"
    data = run(library.library(WS, WEEK, LINEUP, lambda i: i))
    picked = [h for h in data["hooks"] if h["pick"]]
    assert data["picked"] == 1 and picked[0]["pick"]["title"] == LINEUP["primary"][0]["title"]
    assert library.hooks_for_week(WS, WEEK) == {"a" * 8: ["Proof pops in under you"]}
    run(library.unpick(WS, WEEK, "proof-pop"))
    assert run(library.library(WS, WEEK, LINEUP, lambda i: i))["picked"] == 0
    saved = json.loads(library.store_path(WS).read_text())
    assert saved["weeks"][WEEK] == []


def test_moving_to_a_video_not_this_week_is_refused(store):
    with pytest.raises(library.HookError) as caught:
        run(library.pick(WS, WEEK, "whip-in", LINEUP, "z" * 8))
    assert caught.value.status == 400


def test_a_pick_whose_video_left_the_week_is_placed_again_and_says_so(store):
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    smaller = _lineup(("a" * 8, "Should I go ahead"), ("c" * 8, "Done is not done"))
    data = run(library.library(WS, WEEK, smaller, lambda i: i))
    pick = next(h for h in data["hooks"] if h["id"] == "big-number")["pick"]
    assert pick["candidate_id"] in ("a" * 8, "c" * 8)
    assert pick["why"].startswith("Its video left this week's list.")


def test_a_damaged_store_reads_as_empty(store):
    path = library.store_path(WS)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert library.read_store(WS) == {"favorites": [], "weeks": {}}


def _client(monkeypatch, store, scoped=False):
    from tce.api.routers import hooks as hooks_router
    from tce.api.private_access import require_private_workspace
    from tce.api.routers.editorial import get_editorial_sessionmaker

    async def fake_lineup(_sm, _ws):
        return LINEUP

    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    monkeypatch.setattr(hooks_router, "_week_key", lambda: WEEK)
    monkeypatch.setattr(hooks_router, "scoped_editor_workspace", lambda key: WS if scoped else None)
    app = FastAPI()
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[require_private_workspace] = lambda: WS
    app.dependency_overrides[get_editorial_sessionmaker] = lambda: None
    return TestClient(app)


def test_api_library_pick_favorite_and_preview(monkeypatch, store):
    client = _client(monkeypatch, store)
    got = client.get("/api/v1/hooks")
    assert got.status_code == 200 and len(got.json()["hooks"]) == 10
    assert got.json()["hooks"][0]["preview_url"] == "hooks/word-behind/preview"
    picked = client.post("/api/v1/hooks/big-number/pick", json={})
    assert picked.status_code == 200 and picked.json()["picked"] == 1
    fav = client.post("/api/v1/hooks/whip-in/favorite", json={"on": True})
    assert fav.json()["favorite"] is True
    clip = client.get("/api/v1/hooks/whip-in/preview")
    assert clip.status_code == 200 and clip.headers["content-type"] == "video/mp4"
    assert client.get("/api/v1/hooks/nope/preview").status_code == 404
    assert client.post("/api/v1/hooks/nope/pick", json={}).status_code == 404
    gone = client.delete("/api/v1/hooks/big-number/pick")
    assert gone.status_code == 200 and gone.json()["picked"] == 0


def test_api_refuses_a_client_login(monkeypatch, store):
    client = _client(monkeypatch, store, scoped=True)
    assert client.get("/api/v1/hooks").status_code == 403
    assert client.get("/api/v1/hooks/whip-in/preview").status_code == 403


def test_hooks_page_route_and_client_hide():
    from pathlib import Path

    import tce.api.dashboard as dashboard

    src = Path(dashboard.__file__).read_text()
    assert '@router.get("/hooks", response_class=HTMLResponse' in src
    assert src.count(".hooks-entry") >= 2
    js = (Path(dashboard.__file__).parent / "workspace.js").read_text()
    assert 'name: "hooks"' in js and "renderHooks" in js and 'data-go="/hooks"' in js
