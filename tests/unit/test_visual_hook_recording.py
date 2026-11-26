"""The recording screen shows the visual hook picked for that video (T-25711).

Each proved hook carries two or three lines on where to stand, hands and body, and
when to move; the library answers which hooks sit on one video this week; the
recording page reads that before he presses record. Synthetic values."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tce.hooks import catalog, library
from tce.settings import settings

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
NODE = shutil.which("node")
WS = uuid.UUID("00000000-0000-4000-8000-000000025711")
WEEK = "2026-11-23"
LINEUP = {
    "primary": [
        {"candidate_id": "a" * 8, "title": "Should I go ahead is not a decision", "big_idea": "", "reason": "", "filmed": False},
        {"candidate_id": "b" * 8, "title": "Some clients rebook at 80%", "big_idea": "", "reason": "", "filmed": False},
    ],
    "reserve": [],
}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path))
    return tmp_path


def test_every_hook_has_two_or_three_coaching_lines():
    for hook in catalog.HOOKS:
        assert 2 <= len(hook.coach) <= 3, hook.id
        for line in hook.coach:
            assert line.strip() and len(line) <= 110, (hook.id, line)
            assert "\u2014" not in line and "--" not in line, (hook.id, line)


def test_for_video_reads_only_that_videos_picks(store):
    asyncio.run(library.pick(WS, WEEK, "big-number", LINEUP))
    asyncio.run(library.pick(WS, WEEK, "whip-in", LINEUP, "a" * 8))
    on_b = library.for_video(WS, WEEK, "b" * 8)
    assert [h["id"] for h in on_b] == ["big-number"]
    assert on_b[0]["coach"] == list(catalog.BY_ID["big-number"].coach)
    assert "80%" in on_b[0]["why"] and on_b[0]["chosen_by"] == "tce"
    assert [h["id"] for h in library.for_video(WS, WEEK, "a" * 8)] == ["whip-in"]
    assert library.for_video(WS, WEEK, "z" * 8) == []
    assert library.for_video(WS, "2026-11-30", "b" * 8) == []


def _client(monkeypatch, scoped=False):
    from tce.api.private_access import require_private_workspace
    from tce.api.routers import hooks as hooks_router
    from tce.api.routers.editorial import get_editorial_sessionmaker

    monkeypatch.setattr(hooks_router, "_week_key", lambda: WEEK)
    monkeypatch.setattr(hooks_router, "scoped_editor_workspace", lambda key: WS if scoped else None)
    app = FastAPI()
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[require_private_workspace] = lambda: WS
    app.dependency_overrides[get_editorial_sessionmaker] = lambda: None
    return TestClient(app)


def test_api_hooks_for_a_video(monkeypatch, store):
    asyncio.run(library.pick(WS, WEEK, "big-number", LINEUP))
    client = _client(monkeypatch)
    got = client.get("/api/v1/hooks/for/" + "b" * 8)
    assert got.status_code == 200
    body = got.json()
    assert body["week_start"] == WEEK and body["hooks"][0]["preview_url"] == "hooks/big-number/preview"
    assert client.get("/api/v1/hooks/for/" + "a" * 8).json()["hooks"] == []
    # the preview route still answers next to the new one
    assert client.get("/api/v1/hooks/big-number/preview").status_code == 200
    assert _client(monkeypatch, scoped=True).get("/api/v1/hooks/for/" + "b" * 8).status_code == 403


def _model(payload):
    source = (API / "recording.js").read_text(encoding="utf-8")
    fn = re.search(r"^function visualHookModel\(.*?^\}\r?$", source, re.M | re.S).group(0)
    script = fn + f"\nprocess.stdout.write(JSON.stringify(visualHookModel({json.dumps(payload)}, '/tce/api/v1')));"
    return json.loads(subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True, timeout=30).stdout)


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_recording_page_model():
    assert _model(None) == {"show": False, "hooks": []}
    assert _model({"hooks": []})["show"] is False
    hook = {"id": "big-number", "name": "Big number", "what": "Your number fills the screen.",
            "record": "Say the number.", "coach": ["Stand at arm's length.", "Hands low.", "Say the number."]}
    model = _model({"hooks": [hook]})
    assert model["show"] and model["title"] == "Big number" and model["coach"] == hook["coach"]
    assert model["clip"] == "/tce/api/v1/hooks/big-number/preview"
    assert model["tip"] == "Visual hook: Big number. Stand at arm's length."
    two = _model({"hooks": [hook, {**hook, "id": "whip-in", "name": "Whip into the first line", "coach": []}]})
    assert two["what"].endswith("Also picked for this video: Whip into the first line.")
    bare = _model({"hooks": [{**hook, "coach": []}]})
    assert bare["coach"] == ["Say the number."]


def test_recording_page_wires_the_panel():
    html = (API / "recording.html").read_text(encoding="utf-8")
    js = (API / "recording.js").read_text(encoding="utf-8")
    css = (API / "recording.css").read_text(encoding="utf-8")
    for el in ("visualHook", "visualHookTitle", "visualHookHow", "visualHookSheet", "visualHookSheetTitle",
               "visualHookClip", "visualHookWhat", "visualHookCoach", "visualHookReady", "cameraHookTip"):
        assert f'id="{el}"' in html, el
    # the one-line reminder sits in the script heading; the sheet is its own screen
    assert html.index('id="hookPanel"') < html.index('id="visualHook"') < html.index('id="hookChooser"')
    assert html.index('id="visualHookSheet"') < html.index('id="studioView"')
    assert "paintVisualHook(idea);" in js and "idea.visual_hooks" in js and "window.TCE_SCOPED" in js
    assert "/hooks/for/" not in js  # no second request: the recording list carries it
    assert "tce-visual-hook-seen-" in js
    assert ".visual-hook-sheet { position: fixed; inset: 0;" in css and "background: var(--white)" in css
