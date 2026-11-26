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


def _youtube(monkeypatch, key="k", fail=False, files=""):
    monkeypatch.setattr(settings, "youtube_api_key", key)
    monkeypatch.setattr(settings, "youtube_key_files", files)
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


def test_key_from_the_first_file_that_holds_one(monkeypatch, store, tmp_path):
    missing = tmp_path / "nope.env"
    empty = tmp_path / "empty.env"
    empty.write_text("TCE_YOUTUBE_API_KEY=\nOTHER=x\n", encoding="utf-8")
    karaoke = tmp_path / "karaoke.env"
    karaoke.write_text('# app\nexport YOUTUBE_API_KEY="from-karaoke"\nNEXT=1\n', encoding="utf-8")
    seen = []
    calls = _youtube(monkeypatch, key="", files=f"{missing}, {empty},{karaoke}")

    async def search(k, query):
        seen.append(k)
        return ["v1"]

    monkeypatch.setattr(trending, "_search_shorts", search)
    page = run(trending.look(WS))
    assert page["state"] == "ok" and set(seen) == {"from-karaoke"} and calls["ids"] == ["v1"]
    own = tmp_path / "own.env"
    own.write_text("TCE_YOUTUBE_API_KEY=own\n", encoding="utf-8")
    monkeypatch.setattr(settings, "youtube_key_files", f"{own},{karaoke}")
    assert trending.youtube_key() == "own"
    monkeypatch.setattr(settings, "youtube_api_key", "setting")
    assert trending.youtube_key() == "setting"


def test_unreadable_key_file_is_no_key(monkeypatch, store, tmp_path):
    locked = tmp_path / "locked.env"
    locked.write_text("YOUTUBE_API_KEY=x\n", encoding="utf-8")
    locked.chmod(0)
    calls = _youtube(monkeypatch, key="", files=str(locked))
    try:
        page = run(trending.look(WS))
    finally:
        locked.chmod(0o600)
    if page["state"] != "no_key":  # running as root reads a 000 file
        pytest.skip("root reads the file")
    assert calls["search"] == 0


def _http_error(reason):
    import httpx

    req = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/search")
    resp = httpx.Response(403 if reason != "keyInvalid" else 400, request=req,
                          json={"error": {"errors": [{"reason": reason}]}})
    return httpx.HTTPStatusError("refused", request=req, response=resp)


def test_a_key_youtube_turns_down_is_not_called_quota(monkeypatch, store):
    calls = _youtube(monkeypatch)

    async def refuse(k, query):
        calls["search"] += 1
        raise _http_error("keyInvalid")

    monkeypatch.setattr(trending, "_search_shorts", refuse)
    page = run(trending.look(WS, again=True))
    assert page["state"] == "refused" and "did not accept the key" in page["said"]
    assert calls["search"] == 1  # stops at the first refusal


def test_quota_reason_is_still_quota(monkeypatch, store):
    calls = _youtube(monkeypatch)

    async def spent(k, query):
        calls["search"] += 1
        raise _http_error("quotaExceeded")

    monkeypatch.setattr(trending, "_search_shorts", spent)
    page = run(trending.look(WS, again=True))
    assert page["state"] == "quota" and calls["search"] == len(trending.QUERIES)
