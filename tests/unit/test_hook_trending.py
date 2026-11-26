"""The trending video studio inside the hook studio (T-25711). YouTube is stubbed."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tce.hooks import library, trending
from tce.settings import settings

WS = uuid.UUID("00000000-0000-4000-8000-0000000257a6")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def _youtube(monkeypatch, key="k", fail=False):
    monkeypatch.setattr(settings, "youtube_api_key", key)
    calls = {"search": 0}

    async def search(k, query):
        calls["search"] += 1
        if fail:
            raise RuntimeError("403")
        return ["v1", "v2"] if query == trending.QUERIES[0] else ["v2", "v3"]

    async def stats(self, ids):
        calls["ids"] = sorted(ids)
        rows = {"v1": 10, "v2": 900, "v3": 50}
        return [{"video_id": i, "title": f"Title {i}", "channel": "C", "views": rows[i] * 10,
                 "views_per_hour": rows[i], "hours_old": 10} for i in ids]

    monkeypatch.setattr(trending, "_search_shorts", search)
    monkeypatch.setattr(trending.YouTubeDemandService, "fetch_video_stats", stats)
    return calls


def test_no_key_says_so_and_looks_up_nothing(monkeypatch, store):
    calls = _youtube(monkeypatch, key="")
    page = run(trending.look(WS))
    assert page["state"] == "no_key" and "no YouTube key" in page["said"] and calls["search"] == 0


def test_ranked_by_views_an_hour_saved_and_reused(monkeypatch, store):
    calls = _youtube(monkeypatch)
    page = run(trending.look(WS))
    assert [v["video_id"] for v in page["videos"]] == ["v2", "v3", "v1"]
    assert calls["ids"] == ["v1", "v2", "v3"] and calls["search"] == len(trending.QUERIES)
    assert page["videos"][0]["url"] == "https://www.youtube.com/shorts/v2"
    assert "not its picture" in page["note"]
    run(trending.look(WS))
    assert calls["search"] == len(trending.QUERIES)  # fresh: no second lookup
    run(trending.look(WS, again=True))
    assert calls["search"] == 2 * len(trending.QUERIES)


def test_quota_keeps_the_last_list(monkeypatch, store):
    _youtube(monkeypatch)
    run(trending.look(WS))
    _youtube(monkeypatch, fail=True)
    page = run(trending.look(WS, again=True))
    assert page["state"] == "quota" and len(page["videos"]) == 3


def test_consider_puts_it_on_the_list_once_and_keeps_the_rest(monkeypatch, store):
    _youtube(monkeypatch)
    run(library.toggle_favorite(WS, "whip-in", True))
    run(trending.look(WS))
    page = run(trending.consider(WS, "v2"))
    page = run(trending.consider(WS, "v2"))
    assert [p["video_id"] for p in page["proposals"]] == ["v2"]
    assert next(v for v in page["videos"] if v["video_id"] == "v2")["considered"] is True
    assert library.read_store(WS)["favorites"] == ["whip-in"]
    run(library.toggle_favorite(WS, "punch-in", True))  # a later save keeps both lists
    assert library.read_store(WS)["proposals"][0]["video_id"] == "v2" and library.read_store(WS)["trending"]
    with pytest.raises(library.HookError):
        run(trending.consider(WS, "nope"))


def test_api_and_page(monkeypatch, store):
    from tce.api.private_access import require_private_workspace
    from tce.api.routers import hooks as hooks_router

    _youtube(monkeypatch)
    monkeypatch.setattr(hooks_router, "scoped_editor_workspace", lambda key: None)
    app = FastAPI()
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[require_private_workspace] = lambda: WS
    client = TestClient(app)
    got = client.get("/api/v1/hooks/trending")
    assert got.status_code == 200 and got.json()["state"] == "ok"
    assert client.post("/api/v1/hooks/trending/v3/consider").json()["proposals"][0]["video_id"] == "v3"
    assert client.post("/api/v1/hooks/trending/zzz/consider").status_code == 404
    js = (Path(__file__).resolve().parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert 'data-hook-trending="look"' in js and "Consider as a hook" in js and "function trendingHtml(t)" in js
