"""A client login with its own call seat talks (29-Oct, Ziv on Connie: "need to have a button
for talk about the whole week ... all talk to features on tce need to work for her!").

Since 5-Oct a client's own login had no mic: every Talk button opened KM BOT's /voice with
the owner's tce seat, outside the client's fence. A workspace listed in
TCE_CLIENT_VOICE_SEATS now gets every Talk button, opening its own seat on its own host; a
client workspace not listed keeps no mic, and the owner's pages are unchanged.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.settings import settings

CONNIE = uuid.UUID("7247b8fa-d627-4357-b6e8-ca2a26cd4b14")
MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
ZIV_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
OWNER_KEY = "owner-key-" + uuid.uuid4().hex
CONNIE_KEY = "connie-key-" + uuid.uuid4().hex
MATAN_KEY = "matan-key-" + uuid.uuid4().hex
API_DIR = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"


@pytest.fixture
def pages(monkeypatch):
    from fastapi import FastAPI

    from tce.api import dashboard
    from tce.api.private_access import ScopedEditorGuard

    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(ZIV_WS))
    monkeypatch.setattr(
        settings, "editor_workspace_keys", SecretStr(f"{CONNIE_KEY}:{CONNIE},{MATAN_KEY}:{MATAN}")
    )
    monkeypatch.setattr(settings, "client_voice_seats", f"{CONNIE}:tce-connie")
    monkeypatch.setattr(settings, "workspace_languages", "")

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    app = FastAPI()
    app.include_router(dashboard.router)
    app.add_middleware(ScopedEditorGuard)
    return TestClient(app)


def _hidden(html: str) -> str:
    found = re.search(r"<style id=\"tce-scoped\">([^<]*)</style>", html)
    assert found, html[:400]
    return found.group(1)


@pytest.mark.parametrize("path", ["/record", "/today", "/topics", "/library"])
def test_her_login_shows_every_talk_button_and_names_her_seat(pages, path):
    html = pages.get(path, headers={"X-TCE-Editor-Key": CONNIE_KEY}).text
    hidden = _hidden(html)
    for sel in ("#talkHeader", "#talkFab"):
        assert sel not in hidden
    assert ".kmbot-link" in hidden and ".solo-entry" in hidden  # still outside her fence
    assert 'window.TCE_VOICE_SEAT = "tce-connie"' in html and "window.TCE_SCOPED = true" in html


@pytest.mark.parametrize("path", ["/record", "/today"])
def test_a_client_without_a_seat_keeps_no_mic(pages, path):
    html = pages.get(path, headers={"X-TCE-Editor-Key": MATAN_KEY}).text
    hidden = _hidden(html)
    assert "#talkHeader" in hidden and "#talkFab" in hidden
    assert "TCE_VOICE_SEAT" not in html


def test_the_owner_pages_are_unchanged(pages):
    html = pages.get("/today", headers={"X-TCE-Editor-Key": OWNER_KEY}).text
    assert "tce-scoped" not in html and "TCE_VOICE_SEAT" not in html


def test_a_bad_seat_entry_is_ignored(monkeypatch):
    from tce.api import dashboard

    monkeypatch.setattr(settings, "client_voice_seats", f"{CONNIE}:Bad Seat\";alert(1),nonsense,:x")
    assert dashboard.voice_seat(CONNIE) == ""
    monkeypatch.setattr(settings, "client_voice_seats", f" {MATAN}:tce-matan , {CONNIE}:tce-connie ")
    assert dashboard.voice_seat(CONNIE) == "tce-connie" and dashboard.voice_seat(ZIV_WS) == ""


def test_every_call_link_takes_the_seat_from_the_page():
    """No Talk door still hardcodes the owner's seat: the bar, the header mic, the Library's
    call on a held video, the notes sheet's call and its sign-in link."""
    workspace = (API_DIR / "workspace.js").read_text(encoding="utf-8")
    recording = (API_DIR / "recording.js").read_text(encoding="utf-8")
    sheet = (API_DIR / "talk-voice.js").read_text(encoding="utf-8")
    for name, js in (("workspace.js", workspace), ("recording.js", recording), ("talk-voice.js", sheet)):
        assert "seat=tce&" not in js, name
        assert 'seat: "tce"' not in js, name
    assert workspace.count("window.TCE_SCOPED ?") == 0  # every Talk button asks talkOn()
    assert "seat: voiceSeat()," in workspace
    assert "window.TCE_VOICE_SEAT" in recording
