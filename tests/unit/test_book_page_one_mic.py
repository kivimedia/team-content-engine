"""The Book opens on one microphone, and the editor speaks first (25-Nov, T-25211).

Ziv, 25-Nov: "When I go into the book part they put a button for chatting, it is super weird,
it should have been just a microphone on the top ... I go in, I start a conversation and I
understand what's going on with the context of what was written already."

The microphone at the top dials the editor with his mic live, without popping the keyboard,
and its first line carries where he is, the short version of the book the editor keeps
(GET /book/catch-up), the last chapter and the next as the editor summed them up, and the ask
to speak first and then take the next chapter's layout. While they talk the chapter redraws
when the editor records his layout approval. Stubbed server: test_book_page_typed_chat.py's.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from tce.api.routers.book import catch_up
from tests.unit.test_book_page_typed_chat import FAKE_VOICE, Editor, _open
from tests.unit.test_book_page_wait_less import READY_16, _until, _view, sync_playwright

CATCH_UP = {
    "updated": "2026-11-23T21:21:14Z",
    "overview": "The other half has five parts and 53 chapters: you wrote 1 to 11.",
    "chapters": {"13": "The bakery: how the bakery came back. More: the oven story.",
                 "14": "The fair: three stalls in a row. More: the rain day."},
}


VOICE = FAKE_VOICE.replace("start(opts) {", "start(opts) { window.__voiceOn = opts.on;")


class Mic(Editor):
    def __call__(self, route):
        if urlsplit(route.request.url).path == "/voice-client.js":
            self.calls.append(("VOICE", None))
            return route.fulfill(body=VOICE, content_type="application/javascript")
        if urlsplit(route.request.url).path == "/api/v1/book/catch-up":
            self.calls.append(("CATCHUP", None))
            return route.fulfill(json=CATCH_UP)
        return super().__call__(route)


def test_one_microphone_on_top_and_the_old_chat_icons_are_keyboards():
    html = (Path(__file__).resolve().parents[2] / "src" / "tce" / "api" / "book.html").read_text(encoding="utf-8")
    assert html.count('id="bookMic"') == 1
    assert 'aria-label="Type to the editor"' in html
    assert "Chat with the editor about" not in html


def test_the_microphone_dials_the_editor_live_and_its_first_line_is_the_catch_up():
    editor = Mic([_view(13, **READY_16), _view(14)])
    editor.views[13]["status"] = "approved"
    editor.views[13]["phase"] = "approved"
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#bookMic").click()
        _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") > 0)
        start = page.evaluate("() => window.__voice.starts[0]")
        first = page.evaluate("() => window.__voice.sent[0]")
        focused = page.evaluate("() => document.activeElement && document.activeElement.id")
        pressed = page.get_attribute("#bookMic", "aria-pressed")
        panel_open = page.is_visible("#editorPanel")
        browser.close()
    assert start == {"agent": "book-editor", "greet": False, "startMuted": False}
    assert first.startswith("[Where I am in the Book]")
    assert "Speak first" in first
    assert "53 chapters" in first
    assert 'Episode 13 "Episode title 13"' in first and "the bakery came back" in first
    assert 'Episode 14 "Episode title 14" is next' in first and "three stalls" in first
    assert "walk him through the layout of Episode 14" in first
    assert focused != "editorText"
    assert pressed == "true" and panel_open
    assert editor.count("CATCHUP") == 1


def test_on_a_call_the_microphone_is_mute_and_unmute_with_no_second_call():
    editor = Mic([_view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#bookMic").click()
        _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") > 0)
        page.locator("#bookMic").click()
        _until(page, lambda: page.get_attribute("#bookMic", "aria-pressed") == "false")
        starts = page.evaluate("() => window.__voice.starts.length")
        browser.close()
    assert starts == 1


def test_the_layout_redraws_when_the_editor_records_his_approval_on_the_call():
    editor = Mic([_view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor, path="/book/14", wait=False)
        page.locator("#layoutApprove").wait_for()
        page.locator("#bookMic").click()
        _until(page, lambda: page.evaluate("() => (window.__voice && window.__voice.sent.length) || 0") > 0)
        editor.views[14].update(layout_status="approved", phase="approved_unwritten",
                                phase_words="Layout approved, not written", layout_approved_at="2026-11-25T09:00:00")
        page.evaluate("() => window.__voiceOn('turn_end', { text: 'Recorded: the layout of 14 is approved.' })")
        _until(page, lambda: page.is_visible("#writeButton"))
        approve_shown = page.is_visible("#layoutApprove")
        browser.close()
    assert not approve_shown


def test_catch_up_reads_the_editors_short_version(tmp_path):
    f = tmp_path / "book-summary.md"
    f.write_text(
        "<!-- Kept current by book-editor. Updated 2026-11-23T21:21:14Z. -->\n\n"
        "The other half: the short version\n\nFive parts, 53 chapters.\n\n"
        "Part one of five: Understanding the framework (chapters 1 to 15)\n"
        "Chapter 1, The first million was hard: The line every millionaire repeats.\n"
        "  More: You protected yourself with skepticism.\n"
        "Part two of five: Questions\n"
        "Chapter 2, My second million was easy: A tour.\n",
        encoding="utf-8",
    )
    got = catch_up(f)
    assert got["updated"] == "2026-11-23T21:21:14Z"
    assert "53 chapters" in got["overview"] and "Part two" not in got["overview"]
    assert got["chapters"]["1"].startswith("The first million was hard:") and "More: You protected" in got["chapters"]["1"]
    assert set(got["chapters"]) == {"1", "2"}
    assert catch_up(tmp_path / "missing.md") == {"updated": "", "overview": "", "chapters": {}}
