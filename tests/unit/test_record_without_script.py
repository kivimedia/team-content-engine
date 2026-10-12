"""Record without a script (12-Oct, Ziv on a call).

"I want to be able to go into TCE, click record... record with no script... I see
myself... when I'm done and I click on Done, it gets uploaded, transcribed, Jennifer
does editing on it, and it just behaves as a regular video."

A take with no script travels the agent talk's road under the reserved name "_solo":
pieces while he talks, one join, one library video, the edit. Held here:
  1. its video is "Recording, <d Mon>", source solo_take, no agent, and its edit starts;
  2. it is ONE voice: never the conversation rules an agent talk gets;
  3. its name row is not an idea (the agent-talk origin every idea list leaves out);
  4. the Library labels it "Recording", offers Rename (and no Record it again), and the
     rename changes that take's name and nothing else;
  5. a client workspace cannot make one, nor see the button, until Ziv's go;
  6. the page: its button in the studio, its route, and the calls its script makes.
Synthetic data only.
"""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from tce.api import dashboard
from tce.api.routers import agent_talks as talk_routes
from tce.api.routers import production as prod
from tce.editorial import inbox, library
from tce.editorial.common import ORIGIN_AGENT_TALK
from tce.models.editorial import RecordingUpload, TopicCandidate
from tce.models.recording_session import AgentTalk
from tce.production import agent_talks
from tce.settings import settings
from tests.unit.test_agent_talks import (  # noqa: F401 - the fixtures are used by name
    AUTH,
    BASE,
    WS,
    _record,
    _send,
    client,
    needs_ffmpeg,
    spawned,
)

API = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
# 08:30 in Israel on 12-Oct-2026 (UTC+3).
STARTED = "2026-10-12T05:30:00.000Z"


def _solo_body(**over):
    body = {"agent": "_solo", "call_id": str(uuid.uuid4()), "started_at": STARTED, "mime": "video/webm;codecs=vp8,opus"}
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# 1-3. The take becomes a normal library video


def test_a_take_with_no_script_is_named_recording_and_the_day():
    started = agent_talks.parse_instant(STARTED)
    assert agent_talks.talk_title("_solo", started) == "Recording, 12 Oct"
    assert agent_talks.source_for("_solo") == "solo_take"
    assert agent_talks.source_for("atlas") == "agent_talk"
    assert agent_talks.talk_title("atlas", started) == "Talk with Atlas, 12 Oct"
    assert agent_talks.is_solo("_solo") and not agent_talks.is_solo("solo")


@needs_ffmpeg
async def test_done_makes_one_library_video_that_jennifer_edits(client, editorial_sessionmaker, tmp_path, spawned):
    r = await client.post(BASE, headers=AUTH, json=_solo_body())
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Recording, 12 Oct"
    talk = r.json()["talk_id"]
    async with editorial_sessionmaker() as s:
        row = await s.get(AgentTalk, uuid.UUID(talk))
    assert row.status_detail == "Recording: the pieces arrive while you record"

    count = await _send(client, talk, _record(tmp_path / "take.webm", "webm"))
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH,
                          json={"ended_at": "2026-10-12T05:30:04Z", "duration_ms": 3100, "edit": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edit_started"] is True and body["title"] == "Recording, 12 Oct"

    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(body["upload_id"]))
        cand = await s.get(TopicCandidate, upload.candidate_id)
        row = await s.get(AgentTalk, uuid.UUID(talk))
    assert upload.source == "solo_take" and upload.agent_name is None
    assert upload.packet_id is None and upload.archived_at is None and upload.call_transcript == []
    assert upload.status_detail.startswith("Your recording, joined from")
    assert "Jennifer starts the edit now" in upload.status_detail
    assert upload.original_filename.startswith("recording-")
    assert cand.title == "Recording, 12 Oct" and cand.status == "recorded"
    assert row.status_detail.startswith("Finished: your recording is in the library as")
    assert row.join_meta["pieces"] == count
    # The edit started for this video, like any finished take.
    assert len(spawned) == 1 and spawned[0].__name__ == "auto_edit"
    assert spawned[0].cr_frame.f_locals["upload_id"] == upload.id

    # 2. One voice: the edit never treats it as a conversation with an agent.
    assert await prod.talk_voices(upload) is None
    async with editorial_sessionmaker() as s:
        context = await prod._script_context(s, WS, upload)
    assert "no script" in context and "AI agent" not in context and "Recording, 12 Oct" in context

    # 3. Its name row is not an idea: the agent-talk origin no idea list shows.
    assert cand.origin == ORIGIN_AGENT_TALK and ORIGIN_AGENT_TALK in inbox.HIDDEN_ORIGINS

    # 4. The Library: "Recording", Rename, no Record it again; the rename sticks.
    async with editorial_sessionmaker() as s:
        listed = await library.list_library(s, WS)
    item = next(i for i in listed["items"] if i["upload_id"] == str(upload.id))
    keys = [a["key"] for a in item["actions"]]
    assert item["title"] == "Recording, 12 Oct" and item["source"] == "solo_take"
    assert item["source_label"] == "Recording" and item["agent"] is None
    assert "rename" in keys and "re_record" not in keys
    async with editorial_sessionmaker() as s:
        await library.rename_recording(s, WS, upload.id, "  Why   I walk at dawn  ")
        await s.commit()
    async with editorial_sessionmaker() as s:
        listed = await library.list_library(s, WS)
        cand = await s.get(TopicCandidate, upload.candidate_id)
    assert cand.title == "Why I walk at dawn"
    assert next(i for i in listed["items"] if i["upload_id"] == str(upload.id))["title"] == "Why I walk at dawn"


@needs_ffmpeg
async def test_an_agent_talk_is_unchanged(client, editorial_sessionmaker, tmp_path, spawned):
    r = await client.post(BASE, headers=AUTH, json=_solo_body(agent="atlas", call_id="call-0042"))
    talk = r.json()["talk_id"]
    await _send(client, talk, _record(tmp_path / "talk.webm", "webm", seconds=2.0), shuffle=False)
    r = await client.post(f"{BASE}/{talk}/finish", headers=AUTH, json={})
    async with editorial_sessionmaker() as s:
        upload = await s.get(RecordingUpload, uuid.UUID(r.json()["upload_id"]))
    assert upload.source == "agent_talk" and upload.agent_name == "Atlas"
    assert upload.status_detail.startswith("Agent talk with Atlas")
    assert "rename" not in [a["key"] for a in library._actions(upload, 0)]


async def test_only_a_take_with_no_script_is_renamed(editorial_sessionmaker):
    async with editorial_sessionmaker() as s:
        cand = TopicCandidate(workspace_id=WS, week_start=datetime(2026, 10, 12), moment_ids=[], title="An idea",
                              lesson="", audience="both", reasons_to_care=[], public_angle="", gates={},
                              citations_private=[], status="recorded", origin="selector")
        s.add(cand)
        await s.flush()
        walk = RecordingUpload(workspace_id=WS, candidate_id=cand.id, original_filename="walk.mp4",
                               storage_path="/tmp/walk.mp4", sha256="a" * 64, status="edited", job_ids=[])
        s.add(walk)
        await s.flush()
        with pytest.raises(library.LibraryError) as refused:
            await library.rename_recording(s, WS, walk.id, "Something else")
        assert refused.value.status == 409
        walk.source = agent_talks.SOLO_SOURCE
        with pytest.raises(library.LibraryError) as short:
            await library.rename_recording(s, WS, walk.id, " x ")
        assert short.value.status == 422
        await library.rename_recording(s, WS, walk.id, "y" * 300)
        assert cand.title == "y" * library.TITLE_MAX


# ---------------------------------------------------------------------------
# 5. A client workspace waits for Ziv's go


async def test_a_client_workspace_cannot_make_one_yet(client, monkeypatch):
    monkeypatch.setattr(talk_routes, "scoped_editor_workspace", lambda key: WS)
    r = await client.post(BASE, headers=AUTH, json=_solo_body())
    assert r.status_code == 403 and "not on for this workspace" in r.text
    # Its own agent talks are not affected.
    r = await client.post(BASE, headers=AUTH, json=_solo_body(agent="atlas", call_id="call-0043"))
    assert r.status_code == 201
    # On Ziv's go (the setting) it is allowed.
    monkeypatch.setattr(settings, "production_solo_for_clients", True)
    r = await client.post(BASE, headers=AUTH, json=_solo_body())
    assert r.status_code == 201


def _page_client():
    app = FastAPI()
    app.include_router(dashboard.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_the_page_is_the_owners_and_a_client_sees_no_button(monkeypatch):
    async with _page_client() as c:
        page = await c.get("/record/solo")
        studio = await c.get("/record")
        script = await c.get("/recording-solo.js")
    assert page.status_code == 200 and 'id="soloRecord"' in page.text and 'id="soloDone"' in page.text
    assert 'id="soloCamera"' in page.text and 'id="soloStatus"' in page.text
    assert 'id="soloEntry"' in studio.text and "Record without a script" in studio.text
    assert ".solo-entry{display:none" not in studio.text
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]

    monkeypatch.setattr(dashboard, "_scoped_workspace", lambda request: WS)
    monkeypatch.setattr(dashboard, "_page_language", lambda request: "en")
    async with _page_client() as c:
        page = await c.get("/record/solo", follow_redirects=False)
        studio = await c.get("/record")
    assert page.status_code in (302, 307) and page.headers["location"] == "/record"
    assert ".solo-entry{display:none!important}" in studio.text and 'id="tce-scoped"' in studio.text


# ---------------------------------------------------------------------------
# 6. The page's script


def test_the_page_sends_pieces_as_he_talks_and_done_starts_the_edit():
    js = (API / "recording-solo.js").read_text(encoding="utf-8")
    subprocess.run(["node", "--check", str(API / "recording-solo.js")], check=True)
    assert 'const SOLO = "_solo"' in js
    assert '"/agent-talks"' in js and "/chunks/${piece.sequence}" in js and "/finish`" in js
    assert "edit: true" in js
    assert "recorder.start(SLICE_MS)" in js and "const SLICE_MS = 3000" in js
    # Kept on the phone until the server has it, and finished on the next visit.
    assert "indexedDB.open(DB_NAME" in js and "dropPiece(piece.key)" in js
    assert "A take from an earlier visit" in js
    # Progress is a status line, never a blocking screen; Back is never disabled.
    assert "You can leave this page" in js
    assert "soloBack" in js and ".disabled" not in js.split("soloBack", 1)[1].split("\n", 1)[0]
    assert "<dialog" not in (API / "recording-solo.html").read_text(encoding="utf-8")
    assert 'facingMode: "user"' in js
