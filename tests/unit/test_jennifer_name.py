"""The video editor is Jennifer (3-Oct): every place he sees the editor says her name.

"Talk to the editor" is "Talk to Jennifer"; the notes sheet, its status lines, the
library card's sentences and the call seat's brief all name her, and the call seat
has her introduce herself as TCE's video editor who now also checks every edit.
Internal names stay: the jobs still run as "video_editor" and the routes are unchanged.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from tce.api import dashboard
from tce.editorial import library
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.production import autoedit

API = Path(dashboard.__file__).parent
ROOT = API.parents[2]
# How he could read the old name in a sentence: "the editor", "Your editor", "an editor".
OLD_NAME = re.compile(r"\b(the|your|an) editor\b(?!ial)", re.IGNORECASE)


def _strings(js: str) -> list[str]:
    """Every string literal of a script, comments left out."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    js = re.sub(r"(?m)^\s*//.*$", "", js)
    js = re.sub(r"(?<![:\"'\\])//[^\n\"']*$", "", js, flags=re.MULTILINE)
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', js)


def _visible(js: str) -> list[str]:
    return [a or b for a, b in _strings(js)]


@pytest.mark.parametrize("name", ["talk-voice.js", "workspace.js"])
def test_no_sentence_in_the_pages_calls_her_the_editor(name):
    text = (API / name).read_text(encoding="utf-8")
    bad = [s for s in _visible(text) if OLD_NAME.search(s)]
    assert bad == [], bad
    assert "Jennifer" in text


def test_the_notes_sheet_is_talk_to_jennifer():
    html = (API / "workspace.html").read_text(encoding="utf-8")
    assert '<strong id="notesTitle">Talk to Jennifer</strong>' in html
    visible = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    assert not OLD_NAME.search(visible) and "Talk to the editor" not in visible


def test_the_status_lines_of_the_sheet_name_her():
    js = (API / "talk-voice.js").read_text(encoding="utf-8")
    assert 'var EDITOR = "Jennifer";' in js
    for line in (
        'EDITOR + " is reading this note."',
        '"<strong>" + EDITOR + ":</strong> “"',
        '"Connecting " + EDITOR + "\'s voice..."',
        'EDITOR + " stays quiet while the video plays. Pause, then hold to talk."',
        'EDITOR + " is answering out loud. Her answer is written on the note below."',
    ):
        assert line in js, line


async def test_the_rendered_sheet_page_says_talk_to_jennifer(monkeypatch):
    async def on():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", on)
    app = FastAPI()
    app.include_router(dashboard.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        page = await c.get(f"/library/{uuid.uuid4()}/talk")
        voice = await c.get("/talk-voice.js")
    assert page.status_code == 200 and "Talk to Jennifer" in page.text
    assert voice.status_code == 200 and 'var EDITOR = "Jennifer";' in voice.text


async def test_the_library_card_offers_talk_to_jennifer(editorial_sessionmaker):
    ws = uuid.uuid4()
    async with editorial_sessionmaker() as s:
        cand = TopicCandidate(workspace_id=ws, week_start=datetime(2026, 9, 28), moment_ids=["m"],
                              title="A walk", lesson="l", audience="coaches", public_angle="p",
                              gates={}, status="recorded")
        s.add(cand)
        await s.flush()
        s.add(RecordingUpload(workspace_id=ws, candidate_id=cand.id, original_filename="walk.mp4",
                              storage_path="/tmp/walk.mp4", sha256=uuid.uuid4().hex * 2, status="edited",
                              edited_path="/tmp/walk-edited.mp4", transcript=[],
                              edit_plan={"review": {"state": "waiting"}}))
        await s.commit()
        card = (await library.list_library(s, ws))["items"][0]
    labels = {a["key"]: a["label"] for a in card["actions"]}
    assert labels["talk_edit"] == "Talk to Jennifer"
    assert card["review_note"].startswith("Jennifer has not answered yet")
    assert card["source"] is None and card["source_label"] is None  # a walk carries no talk label
    for sentence in (*library.REVIEW_SENTENCES.values(), library.COMMAND_TAKEN, library.EDIT_WAITS):
        assert not OLD_NAME.search(sentence), sentence


def test_the_server_status_lines_name_her():
    source = (API / "routers" / "production.py").read_text(encoding="utf-8")
    sentences = re.findall(r'f?"([^"\n]*)"', source)
    bad = [s for s in sentences if re.search(r"\b[Yy]our editor\b", s)]
    assert bad == [], bad
    assert "Jennifer is reading" in source and "Jennifer marked" in source


def test_internal_names_did_not_change():
    assert autoedit.AGENT_NAME == "video_editor"
    assert autoedit.REVIEW_JOB == "video_edit_review"


def test_the_call_seat_has_her_introduce_herself():
    brief = (ROOT / "deploy" / "voice-seat" / "tce-brief.md").read_text(encoding="utf-8")
    assert "you are Jennifer, TCE's video editor, and from now on you also" in brief
    assert '"Hi, it\'s Jennifer, your video editor. From now on I\n  also check every edit."' in brief
    seat = json.loads((ROOT / "deploy" / "voice-seat" / "tce.json").read_text(encoding="utf-8"))
    video = seat["contexts"]["video"]
    assert video.startswith("You are Jennifer, TCE's video editor, and from now on you also check every edit.")
    for text in (brief, video):
        assert "\u2014" not in text and "\u2013" not in text and "--" not in text
