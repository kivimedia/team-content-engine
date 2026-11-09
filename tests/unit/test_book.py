"""The book app (9-Nov-2026, T-19730): chapters read aloud, a status and an Approve per
chapter, narration that is never bought without his OK, and filmed sessions that ride
the agent talk road as "Book session, episode N" with the reading kept by the edit.
Synthetic text only, plus one read of the real manuscript when it is on this box."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tce.api import dashboard
from tce.api.routers import book as book_routes
from tce.book.store import BookStore, parse_chapters
from tce.production import agent_talks
from tce.settings import settings

OWNER_KEY = "owner-key-" + uuid.uuid4().hex
CLIENT_KEY = "client-key-" + uuid.uuid4().hex
OWNER_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
CLIENT_WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")

MANUSCRIPT = """﻿Book Concept: "The other half"
Chapters to Consider:
Chapter 1 - Listed in the contents only
Part one: Understanding the framework
Chapter 1 - The first million was hard…
You probably heard this line before.
"The first million was hard."
________________
And then you move on.
Chapter 2 - “My second million was easy…”
One paragraph here.

Another one.
Part two: Asking and planning
Outline line that is not a chapter.
"""

REAL = Path("/opt/kmbot-files/doni/book/book2-the-other-half.txt")


def test_chapters_are_the_written_ones_one_paragraph_a_line():
    chapters = parse_chapters(MANUSCRIPT)
    assert [c["n"] for c in chapters] == [1, 2]
    one, two = chapters
    assert one["title"] == "The first million was hard..."
    assert one["part"] == "Part one: Understanding the framework"
    # The table of contents line before the part is not a chapter, a page rule is not text.
    assert one["paragraphs"] == [
        "You probably heard this line before.",
        '"The first million was hard."',
        "And then you move on.",
    ]
    assert two["title"] == "My second million was easy..."
    # The outline after the written part is not read as chapter 2.
    assert two["paragraphs"] == ["One paragraph here.", "Another one."]


@pytest.mark.skipif(not REAL.is_file(), reason="the manuscript is only on the KM BOT box")
def test_the_real_manuscript_has_the_eleven_chapters_of_part_one():
    chapters = parse_chapters(REAL.read_text(encoding="utf-8"))
    assert [c["n"] for c in chapters] == list(range(1, 12))
    words = sum(len(p.split()) for c in chapters for p in c["paragraphs"])
    assert 19000 < words < 23000
    # Every paragraph fits one narration request.
    assert max(len(p) for c in chapters for p in c["paragraphs"]) < 5000


def test_status_survives_a_reimport_only_when_the_text_did_not_change(tmp_path):
    store = BookStore(tmp_path)
    store.import_text(MANUSCRIPT)
    store.set_status(1, "approved", by="ziv")
    store.set_status(2, "approved", by="ziv")
    store.import_text(MANUSCRIPT.replace("Another one.", "Another one, rewritten."))
    assert store.status_of(1)["status"] == "approved"
    assert store.status_of(2)["status"] == "draft"
    with pytest.raises(ValueError):
        store.set_status(1, "published", by="ziv")
    with pytest.raises(KeyError):
        store.set_status(9, "approved", by="ziv")
    with pytest.raises(ValueError):
        store.import_text("no headings at all")


def test_episodes_count_up(tmp_path):
    store = BookStore(tmp_path)
    assert [store.next_episode(), store.next_episode()] == [1, 2]


def test_a_book_session_is_titled_by_episode_and_keeps_the_agent_talk_road():
    started = datetime(2026, 11, 9, 14, 0)
    assert agent_talks.talk_title("_book_7", started) == "Book session, episode 7"
    assert agent_talks.source_for("_book_7") == agent_talks.SOURCE
    assert agent_talks.book_episode("_book_7") == 7
    assert agent_talks.book_episode("atlas") is None
    assert agent_talks.book_episode("_book_x") is None
    assert agent_talks.talk_title("atlas", started) == "Talk with Atlas, 9 Nov"


def test_the_reading_is_a_voice_the_edit_keeps():
    lines = agent_talks.call_lines([
        {"who": "narrator", "text": "The first million was hard.", "t_ms": 0},
        {"who": "ziv", "text": "make that a note", "t_ms": 4000},
    ])
    assert [line["who"] for line in lines] == [agent_talks.AGENT, agent_talks.HOST]
    words = [
        {"text": t, "start_s": i * 0.4, "end_s": i * 0.4 + 0.3}
        for i, t in enumerate(["The", "first", "million", "was", "hard"])
    ] + [
        {"text": t, "start_s": 4.0 + i * 0.4, "end_s": 4.3 + i * 0.4}
        for i, t in enumerate(["make", "that", "a", "note"])
    ]
    voices = agent_talks.voices(words, [
        {"who": "narrator", "text": "The first million was hard.", "t_ms": 0},
        {"who": "ziv", "text": "make that a note", "t_ms": 4000},
    ], "_book_3")
    assert voices.known
    assert voices.agent_words == frozenset(range(5))


# --- the API -----------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch, tmp_path):
    source = tmp_path / "manuscript.txt"
    source.write_text(MANUSCRIPT, encoding="utf-8")
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(OWNER_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{CLIENT_KEY}:{CLIENT_WS}"))
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "book_source_path", str(source))
    monkeypatch.setattr(settings, "book_tts_char_budget", 0)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    app = FastAPI()
    app.include_router(book_routes.router, prefix="/api/v1")
    app.include_router(dashboard.router)
    return TestClient(app)


OWNER = {"X-TCE-Editor-Key": OWNER_KEY}
CLIENT = {"X-TCE-Editor-Key": CLIENT_KEY}


def test_the_chapter_list_imports_on_first_open_and_says_narration_is_off(api):
    r = api.get("/api/v1/book/chapters", headers=OWNER)
    assert r.status_code == 200, r.text
    data = r.json()
    assert [c["title"] for c in data["chapters"]] == ["The first million was hard...", "My second million was easy..."]
    assert all(c["status"] == "draft" and c["status_words"] == "Draft" for c in data["chapters"])
    assert data["narration"]["on"] is False
    assert data["narration"]["spent_chars"] == 0


def test_approve_a_chapter_and_undo_it(api):
    r = api.post("/api/v1/book/chapters/1/status", headers=OWNER, json={"status": "approved"})
    assert r.status_code == 200 and r.json()["status_words"] == "Approved"
    one = api.get("/api/v1/book/chapters/1", headers=OWNER).json()
    assert one["status"] == "approved" and one["next"] == 2 and one["previous"] is None
    assert one["history"][-1]["by"] == "ziv"
    r = api.post("/api/v1/book/chapters/1/status", headers=OWNER, json={"status": "in_review"})
    assert r.json()["status_words"] == "In review"
    assert api.post("/api/v1/book/chapters/1/status", headers=OWNER, json={"status": "gone"}).status_code == 422
    assert api.get("/api/v1/book/chapters/7", headers=OWNER).status_code == 404


def test_no_narration_is_bought_without_a_budget(api, monkeypatch):
    called = []

    class Boom:
        def __init__(self, *a, **k):
            called.append(1)

    monkeypatch.setattr("tce.services.tts.TTSService", Boom)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "configured")
    r = api.get("/api/v1/book/chapters/1/audio/0", headers=OWNER)
    assert r.status_code == 409 and r.json()["device_voice"] is True
    assert called == []
    assert api.get("/api/v1/book/chapters/1/audio/9", headers=OWNER).status_code == 404


def test_narration_inside_the_budget_is_bought_once_then_replayed_free(api, monkeypatch, tmp_path):
    calls = []

    class Fake:
        def __init__(self, *a, output_dir="", **k):
            self.out = Path(output_dir)

        async def generate(self, segments, voice_id=None, **k):
            calls.append((segments[0]["narratorText"], voice_id))
            path = self.out / "voiceover.mp3"
            path.write_bytes(b"ID3fake")

            class R:
                file_path = str(path)

            return R()

    monkeypatch.setattr("tce.services.tts.TTSService", Fake)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "configured")
    monkeypatch.setattr(settings, "book_tts_char_budget", 100)
    first = api.get("/api/v1/book/chapters/1/audio/0", headers=OWNER)
    again = api.get("/api/v1/book/chapters/1/audio/0", headers=OWNER)
    assert first.status_code == 200 and again.status_code == 200 and again.content == b"ID3fake"
    assert len(calls) == 1 and calls[0][1] == settings.book_voice_id
    spent = api.get("/api/v1/book/chapters", headers=OWNER).json()["narration"]["spent_chars"]
    assert spent == len("You probably heard this line before.")
    # The next paragraph would go past the budget: the device reads it, nothing is bought.
    monkeypatch.setattr(settings, "book_tts_char_budget", spent + 5)
    assert api.get("/api/v1/book/chapters/1/audio/1", headers=OWNER).status_code == 409
    assert len(calls) == 1


def test_sessions_hand_out_episode_names_the_talk_road_titles(api):
    one = api.post("/api/v1/book/sessions", headers=OWNER).json()
    two = api.post("/api/v1/book/sessions", headers=OWNER).json()
    assert (one["agent"], one["title"]) == ("_book_1", "Book session, episode 1")
    assert agent_talks.talk_title(two["agent"], datetime(2026, 11, 9)) == "Book session, episode 2"


def test_a_client_login_never_reaches_the_book(api):
    assert api.get("/api/v1/book/chapters", headers=CLIENT).status_code == 403
    assert api.post("/api/v1/book/sessions", headers=CLIENT).status_code == 403
    page = api.get("/book", headers=CLIENT, follow_redirects=False)
    assert page.status_code in (302, 307) and page.headers["location"] == "/today"


def test_the_book_page_and_its_files_are_served(api):
    page = api.get("/book/3", headers=OWNER)
    assert page.status_code == 200
    for element in ("playButton", "talkButton", "approveButton", "filmButton", "chapterList", "filmDone"):
        assert f'id="{element}"' in page.text
    assert api.get("/book.js").status_code == 200
    assert api.get("/book.css").status_code == 200


def test_the_book_tab_sits_beside_the_other_tabs_and_is_hidden_for_clients():
    root = Path(dashboard.__file__).parent
    for name in ("workspace.html", "recording.html"):
        html = (root / name).read_text(encoding="utf-8")
        assert 'data-route="book" class="book-entry"' in html
    assert ".book-entry" in dashboard.SCOPED_HEAD
    assert "/book" not in __import__("tce.api.private_access", fromlist=["x"]).SCOPED_PAGE_PATHS
    for name in ("book.html", "book.js", "book.css"):
        text = (root / name).read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text
