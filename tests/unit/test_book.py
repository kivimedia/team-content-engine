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
    monkeypatch.setattr(settings, "book_editor_record", str(tmp_path / "no-editor" / "chapters.json"))
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


# --- T-19824: the book editor's record is the source -------------------------------
# Ziv, 9-Nov: "The focus on the book app should be to have me check the new episodes you
# write in my voice based on the layout in the file".

import json  # noqa: E402

from tce.book.store import EditorRecord, parse_episode_file  # noqa: E402

LAYOUT_17 = "17. Things that are not frameworks\n    - a sub-bullet he wrote\n    - another one"


def _record(root: Path, entries: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "chapters.json"
    path.write_text(json.dumps({"book": "The other half", "chapters": entries}), encoding="utf-8")
    return path


def _chapter_file(root: Path, n: int, v: int, title: str, lines: list[str]) -> None:
    body = f"<!-- Version {v}: note.\nsecond comment line -->\n\nChapter {n} - {title}\n" + "\n".join(lines) + "\n"
    (root / f"ch{n:02d}-v{v}.md").write_text(body, encoding="utf-8")


@pytest.fixture
def editor(api, monkeypatch, tmp_path):
    root = tmp_path / "book-editor" / "book2"
    path = _record(root, [
        {"part": 1, "number": 1, "title": "The first million was hard", "status": "draft", "version": 1, "file": "ch01-v1.md"},
        {"part": 1, "number": 2, "title": "My second million was easy", "status": "draft", "version": 1, "file": "ch02-v1.md"},
        {"part": 1, "number": 12, "title": "Not frameworks", "status": "in_review", "version": 1, "file": "ch12-v1.md",
         "layout_items": [17], "layout_text": LAYOUT_17},
        {"part": 2, "number": 13, "title": "Asking", "status": "to_write", "version": 0, "file": None,
         "layout_items": [21], "layout_text": "21. Asking and planning"},
    ])
    _chapter_file(root, 1, 1, "The first million was hard\u2026", ["You probably heard this line.", "", "Second paragraph."])
    _chapter_file(root, 2, 1, "My second million was easy", ["One paragraph here."])
    _chapter_file(root, 12, 1, "Not frameworks", ["First written line in his voice.", "Second line."])
    monkeypatch.setattr(settings, "book_editor_record", str(path))
    monkeypatch.setattr(settings, "book_written_through", 1)
    return root


def test_a_chapter_file_drops_its_version_note_and_heading():
    title, paragraphs = parse_episode_file("<!-- v2\nmore -->\n\nChapter 12 - Not frameworks\nA line.\n________\nB line.\n")
    assert title == "Not frameworks" and paragraphs == ["A line.", "B line."]


def test_the_list_reads_the_editors_record_new_episodes_and_still_to_write(api, editor):
    data = api.get("/api/v1/book/chapters", headers=OWNER).json()
    assert data["source"] == "editor"
    by_n = {c["n"]: c for c in data["chapters"]}
    assert [c["n"] for c in data["chapters"]] == [1, 2, 12, 13]
    assert by_n[1]["group"] == "written" and by_n[2]["group"] == "new"
    assert by_n[12]["status"] == "in_review" and by_n[12]["paragraphs"] == 2
    assert by_n[12]["layout_items"] == [17] and by_n[12]["layout_text"] == LAYOUT_17
    assert by_n[13]["status"] == "to_write" and by_n[13]["status_words"] == "Still to write"
    assert by_n[13]["paragraphs"] == 0 and by_n[13]["minutes"] == 0 and by_n[13]["part"] == "Part two"
    one = api.get("/api/v1/book/chapters/13", headers=OWNER).json()
    assert one["paragraphs"] == [] and one["layout_text"] == "21. Asking and planning" and one["previous"] == 12


def test_a_new_episode_and_a_rewrite_appear_by_themselves(api, editor):
    data = json.loads((editor / "chapters.json").read_text())
    data["chapters"][3].update(status="draft", version=1, file="ch13-v1.md")
    (editor / "chapters.json").write_text(json.dumps(data))
    _chapter_file(editor, 13, 1, "Asking", ["Now written."])
    _chapter_file(editor, 12, 2, "Not frameworks", ["Rewritten line.", "Another.", "Third."])
    by_n = {c["n"]: c for c in api.get("/api/v1/book/chapters", headers=OWNER).json()["chapters"]}
    assert by_n[13]["status"] == "draft" and by_n[13]["paragraphs"] == 1
    assert by_n[12]["version"] == 2 and by_n[12]["paragraphs"] == 3
    assert api.get("/api/v1/book/chapters/12", headers=OWNER).json()["paragraphs"][0] == "Rewritten line."


def test_approve_is_written_into_the_editors_record_and_a_rewrite_reopens_it(api, editor):
    r = api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "approved"})
    assert r.status_code == 200, r.text
    entry = json.loads((editor / "chapters.json").read_text())["chapters"][2]
    assert entry["status"] == "approved" and entry["approved_version"] == 1 and entry["approved_at"]
    assert entry["status_history"][-1]["by"] == "ziv"
    assert entry["layout_text"] == LAYOUT_17  # the editor's fields are kept
    assert (editor / "chapters.json").stat().st_mode & 0o020  # the editor can go on writing it
    assert not list(editor.glob(".chapters.json.*.tmp"))
    assert api.get("/api/v1/book/chapters/12", headers=OWNER).json()["status"] == "approved"
    # The editor saves a rewrite: his yes was for version 1, so version 2 waits for a new look.
    _chapter_file(editor, 12, 2, "Not frameworks", ["Rewritten."])
    assert api.get("/api/v1/book/chapters/12", headers=OWNER).json()["status"] == "in_review"
    # Undo keeps the record and the app in step.
    api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "in_review"})
    entry = json.loads((editor / "chapters.json").read_text())["chapters"][2]
    assert entry["status"] == "in_review" and entry["approved_at"] is None and "approved_version" not in entry
    # Nothing to approve on an episode not written yet; nothing kept on TCE's side.
    assert api.post("/api/v1/book/chapters/13/status", headers=OWNER, json={"status": "approved"}).status_code == 422
    assert not (Path(settings.evidence_upload_dir) / "book" / "chapters.json").exists()


def test_an_approve_that_cannot_be_written_changes_nothing(api, editor, monkeypatch):
    def refuse(*a, **k):
        raise PermissionError("read only")

    monkeypatch.setattr("tce.book.store.os.replace", refuse)
    r = api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "approved"})
    assert r.status_code == 503
    assert json.loads((editor / "chapters.json").read_text())["chapters"][2]["status"] == "in_review"
    assert not list(editor.glob(".chapters.json.*.tmp"))


def test_the_real_editor_record_reads_when_it_is_on_this_box():
    real = Path("/opt/kmbot-files/book-editor/book2/chapters.json")
    if not real.is_file():
        pytest.skip("the editor's record is not on this machine")
    chapters = EditorRecord(real, 11).chapters()
    written = [c for c in chapters if c["group"] == "written"]
    assert len(written) == 11 and all(c["paragraphs"] for c in written)
    assert written[0]["title"].startswith("The first million")


def test_the_page_opens_on_the_new_episodes_with_part_one_folded():
    html = (Path(dashboard.__file__).parent / "book.html").read_text(encoding="utf-8")
    js = (Path(dashboard.__file__).parent / "book.js").read_text(encoding="utf-8")
    for needle in ('id="newHead"', 'id="writtenFold"', "Part one, already written", 'id="layoutBox"', 'id="notWritten"'):
        assert needle in html
    assert html.index('id="chapterList"') < html.index('id="writtenFold"')
    assert "Approve this episode" in js and "still to write" in js
