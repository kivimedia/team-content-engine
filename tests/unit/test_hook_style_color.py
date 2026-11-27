"""His color for every hook and headline in the Creatorz edit (T-25711). Synthetic values."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tce.hooks import library
from tce.production.creatorz import reels
from tce.settings import settings

WS = uuid.UUID("00000000-0000-4000-8000-0000000257a5")
WEEK = "2026-11-23"
LINEUP = {"primary": [{"candidate_id": "a" * 8, "title": "x", "filmed": False}], "reserve": []}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


def _luminance(hex_):
    def chan(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def test_every_swatch_is_light_enough_for_the_3d_letters():
    for hex_, name in library.SWATCHES:
        assert _luminance(hex_) >= 0.3, (name, hex_)


def test_saving_reading_and_clearing_the_color_keeps_the_rest(store):
    run(library.toggle_favorite(WS, "whip-in", True))
    run(library.pick(WS, WEEK, "big-number", LINEUP))
    assert library.accent_rgb(WS) is None
    run(library.set_accent(WS, "#2ea3f2"))
    assert library.accent_rgb(WS) == [46, 163, 242]
    run(library.toggle_favorite(WS, "punch-in", True))  # a later save keeps the color
    assert library.accent_rgb(WS) == [46, 163, 242]
    data = run(library.library(WS, WEEK, LINEUP, lambda i: i))
    assert data["style"]["accent"] == "#2EA3F2" and len(data["style"]["swatches"]) == 6
    assert data["favorites"] == 2 and data["picked"] == 1
    run(library.set_accent(WS, None))
    assert library.accent_rgb(WS) is None
    with pytest.raises(library.HookError):
        run(library.set_accent(WS, "#101010"))


def test_the_editor_gets_the_color():
    plan = reels.reel_plan(src=Path("a.mp4"), words_path=Path("w.json"), keep=[[0, 1]], lang="en",
                           work=Path("/tmp/x"), moments=[], punchline=None, bed=None, accent=[46, 163, 242])
    assert plan["accent"] == [46, 163, 242]
    plain = reels.reel_plan(src=Path("a.mp4"), words_path=Path("w.json"), keep=[[0, 1]], lang="en",
                            work=Path("/tmp/x"), moments=[], punchline=None, bed=None)
    assert "accent" not in plain
    src = (Path(__file__).resolve().parents[2] / "src/tce/api/routers/production.py").read_text(encoding="utf-8")
    assert "hook_library.accent_rgb(ws)" in src


def test_api_and_page(monkeypatch, store):
    from tce.api.private_access import require_private_workspace
    from tce.api.routers import hooks as hooks_router
    from tce.api.routers.editorial import get_editorial_sessionmaker

    async def fake_lineup(_sm, _ws):
        return LINEUP

    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    monkeypatch.setattr(hooks_router, "_week_key", lambda: WEEK)
    monkeypatch.setattr(hooks_router, "scoped_editor_workspace", lambda key: None)
    app = FastAPI()
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[require_private_workspace] = lambda: WS
    app.dependency_overrides[get_editorial_sessionmaker] = lambda: None
    client = TestClient(app)
    got = client.post("/api/v1/hooks/style", json={"accent": "#FF8A6B"})
    assert got.status_code == 200 and got.json()["style"]["accent"] == "#FF8A6B"
    assert client.post("/api/v1/hooks/style", json={"accent": "#000000"}).status_code == 400
    assert client.post("/api/v1/hooks/style", json={"accent": None}).json()["style"]["accent"] is None
    js = (Path(__file__).resolve().parents[2] / "src/tce/api/workspace.js").read_text(encoding="utf-8")
    assert "function hookStyle(style)" in js and "data-hook-accent" in js and '"/hooks/style"' in js
