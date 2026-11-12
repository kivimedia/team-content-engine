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
    monkeypatch.setattr(settings, "book_layout_seed", "")
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


def test_a_session_is_named_after_the_chapter_it_began_on_not_only_a_running_count(api):
    # 10-Nov (T-20030): his first filmed take began on Episode 12 and the note called it
    # "episode 1". A session now carries the chapter; with none it keeps the old name.
    took = api.post("/api/v1/book/sessions", headers=OWNER, json={"chapter": 2}).json()
    assert took["agent"].startswith("_book_") and took["agent"].endswith("_c2")
    assert took["place"] == "Chapter 2" and took["title"].startswith("Book session on Chapter 2, ")
    started = datetime(2026, 11, 10, 12, 50)
    assert agent_talks.talk_title("_book_1_e12", started) == "Book session on Episode 12, 10 Nov"
    assert agent_talks.talk_title("_book_3_c4", started) == "Book session on Chapter 4, 10 Nov"
    assert agent_talks.book_episode("_book_1_e12") == 1
    assert agent_talks.book_place("_book_1_e12") == "Episode 12"
    assert agent_talks.book_place("_book_1") is None
    assert agent_talks.book_episode("_book_1_x12") is None
    assert agent_talks.source_for("_book_1_e12") == agent_talks.SOURCE
    # A chapter the Book does not hold is not invented: the take keeps the running count.
    ghost = api.post("/api/v1/book/sessions", headers=OWNER, json={"chapter": 999}).json()
    assert ghost["place"] is None and ghost["title"].startswith("Book session, episode ")


def test_a_saved_take_is_drawn_as_good_news_never_in_the_error_colour():
    # 10-Nov (T-20030): "Error" was his one word for a note that his take was kept.
    js = (Path(book_routes.__file__).resolve().parents[1] / "book.js").read_text(encoding="utf-8")
    css = (Path(book_routes.__file__).resolve().parents[1] / "book.css").read_text(encoding="utf-8")
    assert "had no Send or Archive choice" not in js
    assert "Saved in your Library: ${name}, under Archived. You did not pick" in js
    assert '"saved");' in js and ".status-line.saved" in css
    assert "body: JSON.stringify(state.chapter ? { chapter: state.chapter.n } : {})" in js


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


# Since T-20758 a new episode is readable only once its layout is approved; these T-19824
# tests are about reading and approving written text, so their episodes carry an approved
# layout the drafts were written after.
APPROVED_LAYOUT = {"layout": {"big_idea": "An idea.", "covers": ["One thing"], "version": 1},
                   "layout_status": "approved", "layout_approved_version": 1, "layout_approved_draft_version": 0}


@pytest.fixture
def editor(api, monkeypatch, tmp_path):
    root = tmp_path / "book-editor" / "book2"
    path = _record(root, [
        {"part": 1, "number": 1, "title": "The first million was hard", "status": "draft", "version": 1, "file": "ch01-v1.md"},
        {"part": 1, "number": 2, "title": "My second million was easy", "status": "draft", "version": 1, "file": "ch02-v1.md",
         **APPROVED_LAYOUT},
        {"part": 1, "number": 12, "title": "Not frameworks", "status": "in_review", "version": 1, "file": "ch12-v1.md",
         "layout_items": [17], "layout_text": LAYOUT_17, **APPROVED_LAYOUT},
        {"part": 2, "number": 13, "title": "Asking", "status": "to_write", "version": 0, "file": None,
         "layout_items": [21], "layout_text": "21. Asking and planning", **APPROVED_LAYOUT},
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


# --- T-19955: Ziv's 10 Nov call ----------------------------------------------------------

BOOK_DIR = Path(dashboard.__file__).parent


def test_the_book_films_through_the_studio_camera_ladder_not_one_landscape_ask():
    # "When you click the video feature, it shows me zoomed in a lot, not the same as the
    # regular record video of TCE."
    js = (BOOK_DIR / "book.js").read_text(encoding="utf-8")
    solo = (BOOK_DIR / "recording-solo.js").read_text(encoding="utf-8")
    ladder = solo.split("const CAMERA_ATTEMPTS = [", 1)[1].split("];", 1)[0]
    assert ladder in js, "the Book's camera ladder drifted from Record without a script's"
    assert "width: { ideal: 1080 }, height: { ideal: 1920 } },\n        audio" not in js
    assert "function portraitVideo(" in js and "canvas.captureStream(30)" in js
    css = (BOOK_DIR / "book.css").read_text(encoding="utf-8")
    assert "object-fit: contain" in css.split(".film-strip video", 1)[1].split("}", 1)[0]


def test_stop_asks_send_or_archive_and_nothing_finishes_before_the_choice():
    js = (BOOK_DIR / "book.js").read_text(encoding="utf-8")
    html = (BOOK_DIR / "book.html").read_text(encoding="utf-8")
    for element in ("choiceBox", "choiceSend", "choiceArchive"):
        assert f'id="{element}"' in html
    assert "edit: true" not in js
    assert "!take.choice" in js and 'const edit = take.choice === "send"' in js
    # A take from an earlier visit with no choice is archived, never sent.
    assert 'choice: take.choice || "archive"' in js


def test_the_device_voice_says_it_is_the_device_voice():
    js = (BOOK_DIR / "book.js").read_text(encoding="utf-8")
    html = (BOOK_DIR / "book.html").read_text(encoding="utf-8")
    assert 'id="voiceBadge"' in html
    assert "not ElevenLabs" in js and "not ElevenLabs" in html


def test_the_editor_chat_is_an_icon_inside_the_book_never_a_new_tab():
    js = (BOOK_DIR / "book.js").read_text(encoding="utf-8")
    html = (BOOK_DIR / "book.html").read_text(encoding="utf-8")
    assert "window.open(" not in js and "/voice?seat=" not in js
    for element in ("talkButton", "listTalk", "editorPanel", "editorForm", "editorMic"):
        assert f'id="{element}"' in html
    assert ">Talk to the editor<" not in html
    assert 'const EDITOR_AGENT = "book-editor"' in js and "greet: false" in js
    assert "[Where I am in the Book]" in js


class _FakeTTS:
    calls: list = []

    def __init__(self, *a, model="", output_dir="", **k):
        self.model = model
        self.out = Path(output_dir) if output_dir else None

    async def generate(self, segments, voice_id=None, **k):
        _FakeTTS.calls.append((segments[0]["narratorText"], voice_id, self.model))
        path = self.out / "voiceover.mp3"
        path.write_bytes(b"ID3" + voice_id.encode())

        class R:
            file_path = str(path)

        return R()

    async def list_voices(self):
        return [{"voice_id": "maleVoice01", "name": "Brian", "category": "premade", "labels": {"gender": "male", "accent": "american"}},
                {"voice_id": "femVoice01", "name": "Sarah", "category": "premade", "labels": {"gender": "female"}}]


def test_his_voice_pick_reads_from_then_on_on_eleven_v4_without_a_release(api, monkeypatch):
    _FakeTTS.calls = []
    monkeypatch.setattr("tce.services.tts.TTSService", _FakeTTS)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "configured")
    monkeypatch.setattr(settings, "book_tts_char_budget", 1000)
    voices = api.get("/api/v1/book/voices", headers=OWNER).json()
    assert [v["gender"] for v in voices["voices"]] == ["male", "female"]
    sample = api.get("/api/v1/book/voice-sample?voice_id=maleVoice01&chapter=1", headers=OWNER)
    assert sample.status_code == 200 and sample.content == b"ID3maleVoice01"
    assert _FakeTTS.calls[-1][1:] == ("maleVoice01", "eleven_v4")
    # The same sample again is free.
    assert api.get("/api/v1/book/voice-sample?voice_id=maleVoice01&chapter=1", headers=OWNER).status_code == 200
    assert len(_FakeTTS.calls) == 1
    picked = api.post("/api/v1/book/voice", headers=OWNER, json={"voice_id": "maleVoice01", "model": "eleven_v4", "name": "Brian"})
    assert picked.status_code == 200 and picked.json()["narration"]["model"] == "eleven_v4"
    assert api.get("/api/v1/book/chapters/1/audio/0", headers=OWNER).content == b"ID3maleVoice01"
    assert _FakeTTS.calls[-1][1:] == ("maleVoice01", "eleven_v4")
    assert api.post("/api/v1/book/voice", headers=CLIENT, json={"voice_id": "maleVoice01"}).status_code == 403
    assert api.get("/api/v1/book/voice-sample?voice_id=../x", headers=OWNER).status_code == 422


def test_a_sample_is_never_bought_past_the_budget(api, monkeypatch):
    _FakeTTS.calls = []
    monkeypatch.setattr("tce.services.tts.TTSService", _FakeTTS)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "configured")
    monkeypatch.setattr(settings, "book_tts_char_budget", 3)
    assert api.get("/api/v1/book/voice-sample?voice_id=maleVoice01&chapter=1", headers=OWNER).status_code == 409
    assert _FakeTTS.calls == []


def test_eleven_v4_goes_through_text_to_dialogue_and_v2_stays_on_text_to_speech(monkeypatch, tmp_path):
    import asyncio

    import httpx

    from tce.services import tts as tts_mod

    seen = []

    class Resp:
        status_code = 200
        content = b"ID3audio"
        text = ""

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen.append((url, json))
            return Resp()

    monkeypatch.setattr(httpx, "AsyncClient", Client)

    async def no_duration(self, path):
        return 1.0

    monkeypatch.setattr(tts_mod.TTSService, "_detect_duration", no_duration)
    for model in ("eleven_v4", "eleven_multilingual_v2"):
        svc = tts_mod.TTSService(api_key="k", model=model, output_dir=str(tmp_path / model))
        asyncio.run(svc.generate(segments=[{"narratorText": "Hello there."}], voice_id="vid123"))
    (v4_url, v4_body), (v2_url, v2_body) = seen
    assert v4_url.endswith("/text-to-dialogue")
    assert v4_body["inputs"] == [{"text": "Hello there.", "voice_id": "vid123"}] and v4_body["model_id"] == "eleven_v4"
    assert v2_url.endswith("/text-to-speech/vid123") and v2_body["model_id"] == "eleven_multilingual_v2"


def test_choice_box_scrolls_clear_of_the_sticky_top_bar():
    # 10-Nov (T-19982): at 390px Stop scrolled the Send or Archive box under the sticky
    # top bar, hiding the take's name and length.
    css = (Path(book_routes.__file__).resolve().parents[1] / "book.css").read_text(encoding="utf-8")
    rule = css.split(".choice-box {", 1)[1].split("}", 1)[0]
    assert "scroll-margin-top" in rule



# --- T-20758: layout first, then write, then listen --------------------------------------
# Ziv, on a call 12-Nov: he agrees each chapter's layout before any text is written or read
# to him, the way TCE has a big idea, then a script, then a workshop.

SEED_12 = {"number": 12, "big_idea": "Before you label your business, I label mine.",
           "covers": ["Why my own businesses", "The school for balloon artists"],
           "question_for_ziv": "Is each stage label right?", "his_outline": "17. Examples of my businesses",
           "layout_status": "proposed"}
SEED_13 = {"number": 13, "big_idea": "Asking is a plan.", "covers": ["Ask", "Plan"], "question_for_ziv": "",
           "layout_status": "proposed"}


@pytest.fixture
def held(api, monkeypatch, tmp_path):
    root = tmp_path / "held" / "book2"
    path = _record(root, [
        {"part": 1, "number": 1, "title": "The first million was hard", "status": "draft", "version": 1, "file": "ch01-v1.md"},
        {"part": 1, "number": 12, "title": "My businesses", "status": "draft", "version": 1, "file": "ch12-v1.md",
         "layout_items": [17], "layout_text": "17. Examples of my businesses"},
        {"part": 2, "number": 13, "title": "Asking", "status": "to_write", "version": 0, "file": None},
    ])
    _chapter_file(root, 1, 1, "The first million was hard", ["His own words."])
    _chapter_file(root, 12, 1, "My businesses", ["A draft from before the rule.", "Second line."])
    seed = tmp_path / "held" / "layouts.json"
    seed.write_text(json.dumps({"chapters": [SEED_12, SEED_13]}), encoding="utf-8")
    monkeypatch.setattr(settings, "book_editor_record", str(path))
    monkeypatch.setattr(settings, "book_written_through", 11)
    monkeypatch.setattr(settings, "book_layout_seed", str(seed))
    return root


def _entry(root: Path, n: int) -> dict:
    return next(e for e in json.loads((root / "chapters.json").read_text())["chapters"] if e["number"] == n)


def test_a_new_chapter_opens_on_its_layout_and_its_text_never_leaves_the_server(api, held):
    by_n = {c["n"]: c for c in api.get("/api/v1/book/chapters", headers=OWNER).json()["chapters"]}
    assert by_n[1]["phased"] is False and by_n[1]["readable"] is True
    assert by_n[12]["phase"] == "on_hold" and by_n[12]["phase_words"] == "Drafted earlier, on hold"
    assert by_n[12]["readable"] is False and by_n[12]["paragraphs"] == 0 and by_n[12]["minutes"] == 0
    assert by_n[12]["big_idea"] == SEED_12["big_idea"]
    assert by_n[13]["phase"] == "layout" and by_n[13]["phase_words"] == "Layout to approve"
    one = api.get("/api/v1/book/chapters/12", headers=OWNER).json()
    assert one["paragraphs"] == [] and one["held_paragraphs"] == 2
    assert one["layout"]["covers"] == SEED_12["covers"] and one["layout"]["question"] == SEED_12["question_for_ziv"]
    assert one["outline"] == "17. Examples of my businesses"
    # No route reads it: not the audio, not a sample, not a text approve, not a write ask.
    assert api.get("/api/v1/book/chapters/12/audio/0", headers=OWNER).status_code == 423
    assert api.get("/api/v1/book/voice-sample?voice_id=abc123&chapter=12", headers=OWNER).status_code == 423
    assert api.post("/api/v1/book/chapters/12/status", headers=OWNER, json={"status": "approved"}).status_code == 422
    assert api.post("/api/v1/book/chapters/12/write", headers=OWNER, json={}).status_code == 422
    # Part one is his own text and reads as before.
    assert api.get("/api/v1/book/chapters/1", headers=OWNER).json()["paragraphs"] == ["His own words."]


def test_his_note_and_his_yes_go_into_the_editors_record_then_write_waits_for_his_word(api, held):
    r = api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "note", "note": "Put the coaching business first"})
    assert r.status_code == 200, r.text
    assert _entry(held, 12)["layout_notes"][-1]["text"] == "Put the coaching business first"
    r = api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "approve", "by": "dev-test"})
    assert r.status_code == 200, r.text
    assert r.json()["phase"] == "approved_unwritten" and r.json()["phase_words"] == "Layout approved, not written"
    entry = _entry(held, 12)
    assert entry["layout_status"] == "approved" and entry["layout_approved_by"] == "dev-test"
    assert entry["layout"]["big_idea"] == SEED_12["big_idea"]  # what he approved is pinned in the record
    assert entry["layout_approved_draft_version"] == 1 and entry["layout_text"] == "17. Examples of my businesses"
    assert (held / "chapters.json").stat().st_mode & 0o020
    # The draft from before is still held: approving a layout writes nothing and reads nothing.
    assert api.get("/api/v1/book/chapters/12", headers=OWNER).json()["paragraphs"] == []
    assert "write_requested_at" not in entry
    r = api.post("/api/v1/book/chapters/12/write", headers=OWNER, json={"by": "dev-test"})
    assert r.status_code == 200 and r.json()["already"] is False
    assert _entry(held, 12)["write_requested_by"] == "dev-test"
    assert api.post("/api/v1/book/chapters/12/write", headers=OWNER, json={}).json()["already"] is True


def test_only_a_version_written_or_confirmed_after_his_yes_can_be_heard(api, held):
    api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "approve"})
    # The editor confirms the old draft against the approved layout: now it may be heard.
    data = json.loads((held / "chapters.json").read_text())
    data["chapters"][1].update(draft_confirmed_version=1, draft_confirmed_layout_version=1)
    (held / "chapters.json").write_text(json.dumps(data))
    one = api.get("/api/v1/book/chapters/12", headers=OWNER).json()
    assert one["readable"] is True and one["phase"] == "ready" and len(one["paragraphs"]) == 2
    assert api.get("/api/v1/book/chapters/12/audio/0", headers=OWNER).status_code == 409  # device voice, budget 0
    # He reopens the layout: the chapter is held again.
    api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "reopen"})
    assert api.get("/api/v1/book/chapters/12", headers=OWNER).json()["paragraphs"] == []
    # Approved again, then the editor writes version 2 from it: readable without a confirm.
    api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "approve"})
    data = json.loads((held / "chapters.json").read_text())
    data["chapters"][1].pop("draft_confirmed_version")
    (held / "chapters.json").write_text(json.dumps(data))
    assert api.get("/api/v1/book/chapters/12", headers=OWNER).json()["paragraphs"] == []
    _chapter_file(held, 12, 2, "My businesses", ["Written from the approved layout."])
    one = api.get("/api/v1/book/chapters/12", headers=OWNER).json()
    assert one["phase"] == "ready" and one["paragraphs"] == ["Written from the approved layout."]
    # The editor redraws the layout after his yes: it needs his look again and the text is held.
    data = json.loads((held / "chapters.json").read_text())
    data["chapters"][1]["layout"]["version"] = 2
    (held / "chapters.json").write_text(json.dumps(data))
    one = api.get("/api/v1/book/chapters/12", headers=OWNER).json()
    assert one["layout_status"] == "proposed" and one["paragraphs"] == []


def test_a_layout_word_that_cannot_be_written_changes_nothing(api, held, monkeypatch):
    def refuse(*a, **k):
        raise PermissionError("read only")

    monkeypatch.setattr("tce.book.store.os.replace", refuse)
    assert api.post("/api/v1/book/chapters/12/layout", headers=OWNER, json={"action": "approve"}).status_code == 503
    assert "layout_status" not in _entry(held, 12)
    assert not list(held.glob(".chapters.json.*.tmp"))


def test_part_one_has_no_layout_step_and_a_client_cannot_reach_it(api, held):
    assert api.post("/api/v1/book/chapters/1/layout", headers=OWNER, json={"action": "approve"}).status_code == 422
    assert api.post("/api/v1/book/chapters/12/layout", headers=CLIENT, json={"action": "approve"}).status_code == 403
    assert api.post("/api/v1/book/chapters/12/write", headers=CLIENT, json={}).status_code == 403


def test_the_page_opens_a_new_chapter_on_its_layout_with_the_three_steps():
    html = (BOOK_DIR / "book.html").read_text(encoding="utf-8")
    js = (BOOK_DIR / "book.js").read_text(encoding="utf-8")
    for needle in ('id="layoutPlan"', "The layout is right", "Write this chapter", "Workshop this chapter",
                   'id="planNoteForm"', "One question for you", "Your own outline lines", 'id="stepsLine"'):
        assert needle in html, needle
    # The layout sits above where the text would be, and the chat panel stays first in the page.
    assert html.index('id="editorPanel"') < html.index('id="layoutPlan"') < html.index('id="paragraphs"')
    assert "/layout`" in js and "/write`" in js and "drawPlan(c)" in js
    assert "nothing is written or read to him before he approves it" in js  # what the editor hears
    for text in (html, js, (BOOK_DIR / "book.css").read_text(encoding="utf-8")):
        assert "—" not in text and "–" not in text


def test_the_real_record_holds_every_new_chapter_until_its_layout_is_approved():
    real = Path("/opt/kmbot-files/book-editor/book2/chapters.json")
    seed = Path("/opt/kmbot-files/doni/book/book2-layouts-v1.json")
    if not (real.is_file() and seed.is_file()):
        pytest.skip("the editor's record or the layouts are not on this machine")
    chapters = EditorRecord(real, 11, seed=seed).chapters()
    new = [c for c in chapters if c["n"] > 11]
    assert all(not c["readable"] or c["layout_status"] == "approved" for c in new)
    assert all(c["layout"] and c["layout"]["big_idea"] for c in new)
    assert all(c["readable"] and not c["phased"] for c in chapters if c["n"] <= 11)
