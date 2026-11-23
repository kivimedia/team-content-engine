"""The Book's editor chat answers a typed comment without a call (23-Nov, wait-less item F11).

With no call up, a typed comment goes to the editor's own chat in KM BOT (POST
/kmbot-api/message, the app's own send, queue: true) with the same [Where I am in the Book]
line and the same ask about unseen replies, and the editor's answer streams back into the
chat. A call is dialed only when he taps the mic, and a line typed on a call still goes on the
call. KM BOT's side is read while the Book opens, and its voice client is fetched once, behind
the page, only once KM BOT has answered this phone. The history rows have the live API's shape
(his turns carry from "ziv" and origin "you"; tests/browser/book-editor-agent.cjs has the read).
Stubbed server: test_book_page_wait_less.py's, with KM BOT's routes added. Pictures go to
TCE_SHOT_DIR when set.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

from tests.unit.test_book_page_wait_less import READY_16, Book, _shot, _until, _view, sync_playwright

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
NOW = time.time()


def _at(seconds_ago: float) -> str:
    return datetime.fromtimestamp(NOW - seconds_ago, UTC).isoformat().replace("+00:00", "Z")


# He last opened the Book two hours ago: the day-old exchange is seen, the hour-old reply is not.
TURNS = [
    {"run_id": "r1", "at": _at(86400), "from": "ziv", "transport": "api", "origin": "you",
     "message": "Can you tighten chapter 11?", "ack": "On it.", "result": "Tightened chapter 11, it is in review."},
    {"run_id": "r2", "at": _at(3600), "from": "ziv", "transport": "voice", "origin": "you",
     "message": "Is the bakery layout done?", "ack": "Yes: the bakery chapter layout is ready for you.", "result": ""},
]
TASKS = [{"id": "T-1", "title": "Writing episode 15 from your outline", "status": "open", "assigned": "book-editor",
          "blocked_why": None},
         {"id": "T-2", "title": "Someone else's card", "status": "open", "assigned": "dev"}]
SEEN = "try { localStorage.setItem('tce-book-editor-seen', String(Date.now() - 7200000)); } catch (e) {}"
FAKE_VOICE = """
window.__voice = window.__voice || { starts: [], sent: [] };
window.KmVoice = { start(opts) {
  window.__voice.starts.push({ agent: opts.agent, greet: opts.greet, startMuted: opts.startMuted });
  setTimeout(() => opts.on('realtime', {}), 0);
  return { send(t) { window.__voice.sent.push(String(t)); }, stop() {}, mute() {} };
} };
"""
READY = "Ready. Type below, or tap the mic and talk."


def _sse(*events) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


ANSWERED = _sse(
    ("accepted", {"agent": "book-editor", "request": "ab12cd34", "task": None}),
    ("first", {"text": "Checking where the episodes stand.", "smart": True}),
    ("ack", {"text": "Episode 16 is ready to listen, and 14 waits on its layout."}),
    ("result", {"text": "", "single_block": True, "choices": [], "task": None}),
    ("done", {"code": 0}),
)


class Editor(Book):
    """The Book's stub plus KM BOT: the editor's history and list, its send, its voice client."""

    def __init__(self, views):
        super().__init__(views)
        self.signed_in = True
        self.turns = list(TURNS)
        self.messages: list = []
        self.answer = lambda body: (200, "text/event-stream", ANSWERED)
        self.hold_list = False
        self.held: list = []

    def __call__(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/voice-client.js":
            self.calls.append(("VOICE", None))
            if not self.signed_in:
                return route.fulfill(status=401, body="")
            return route.fulfill(body=FAKE_VOICE, content_type="application/javascript")
        if path.startswith("/kmbot-api/"):
            self.calls.append(("KMBOT", path))
            if not self.signed_in:
                return route.fulfill(status=401, body="")
            if path == "/kmbot-api/history":
                return route.fulfill(json={"agent": "book-editor", "view": "chat", "turns": self.turns})
            if path == "/kmbot-api/tasks":
                return route.fulfill(json={"tasks": TASKS})
            if path == "/kmbot-api/message" and request.method == "POST":
                body = json.loads(request.post_data or "{}")
                self.messages.append(body)
                status, kind, text = self.answer(body)
                return route.fulfill(status=status, content_type=kind, body=text)
        if path == "/api/v1/book/chapters" and self.hold_list:
            self.calls.append(("LIST", None))
            self.held.append(route)
            return None
        return super().__call__(route)

    def count(self, kind, what=None):
        return sum(1 for c in self.calls if c[0] == kind and (what is None or c[1] == what))


def _open(pw, editor, path="/book", wait=True):
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    page.add_init_script(SEEN)
    page.route("https://book.test/**", editor)
    page.goto(f"https://book.test{path}")
    if wait:
        page.locator("#listTalk").wait_for()
    return browser, page


def _type(page, text):
    page.fill("#editorText", text)
    page.click("#editorForm button[type=submit]")


def test_a_typed_comment_goes_to_the_editors_chat_and_its_answer_streams_back_with_no_call():
    editor = Editor([_view(14), _view(16, **READY_16)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.locator("#agentCatchup").wait_for()
        _until(page, lambda: editor.count("VOICE") == 1)  # fetched once, behind the page
        page.click("#listTalk")
        _type(page, "Where are we?")
        _until(page, lambda: "ready to listen" in page.inner_text("#editorLog"))
        body = editor.messages[0]
        assert set(body) == {"agent", "text", "source_id", "queue"}
        assert body["agent"] == "book-editor" and body["queue"] is True and re.fullmatch(UUID, body["source_id"])
        # The same line a call's first line carries: where he is, the unseen reply quoted, his words.
        assert body["text"].startswith("[Where I am in the Book] He is on the Book's chapters page")
        assert "1 reply he has not seen" in body["text"] and "bakery chapter layout is ready" in body["text"]
        assert "Tightened chapter 11" not in body["text"]
        assert body["text"].endswith("\n\nZiv: Where are we?")
        assert page.evaluate("window.__voice.starts.length") == 0  # no call was dialed
        log = page.inner_text("#editorLog")
        assert re.search(r"You\s*Where are we\?", log)
        assert "Checking where the episodes stand." in log and "14 waits on its layout" in log
        assert page.inner_text("#editorState") == READY
        assert page.input_value("#editorText") == ""
        # The next comment at the same place carries only his words.
        editor.answer = lambda body: (200, "text/event-stream", _sse(
            ("accepted", {"agent": "book-editor", "request": "ef56ab78"}),
            ("ack", {"text": "Episode 14 waits on one question in its layout: is each stage label right?"}),
            ("result", {"text": "", "single_block": True}), ("done", {"code": 0})))
        _type(page, "And episode 14?")
        _until(page, lambda: "is each stage label right?" in page.inner_text("#editorLog"))
        assert editor.messages[1]["text"] == "And episode 14?"
        assert editor.count("VOICE") == 1 and page.evaluate("window.__voice.starts.length") == 0
        _until(page, lambda: page.inner_text("#editorState") == READY)
        _shot(page, "typed-chat", "editorState", "editorLog", "editorText", "editorMic")
        browser.close()


def test_the_mic_dials_the_call_and_a_line_typed_on_it_goes_on_the_call():
    editor = Editor([_view(14)])
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        _until(page, lambda: editor.count("VOICE") == 1)
        page.click("#listTalk")
        page.click("#editorMic")
        _until(page, lambda: page.evaluate("window.__voice.sent.length") == 1)
        start = page.evaluate("window.__voice.starts")
        assert start == [{"agent": "book-editor", "greet": False, "startMuted": True}]
        assert page.evaluate("window.__voice.sent[0]").startswith("[Where I am in the Book]")
        _type(page, "And now?")
        _until(page, lambda: page.evaluate("window.__voice.sent.length") == 2)
        assert page.evaluate("window.__voice.sent[1]") == "And now?"
        assert editor.messages == []  # nothing went to the chat while the call is up
        # The voice client was fetched once in all: the probe's own bytes ran as the script.
        assert editor.count("VOICE") == 1
        _shot(page, "on-call", "editorState", "editorText", "editorMic")
        browser.close()


def test_a_busy_editor_takes_it_in_turn_and_the_answer_comes_from_its_chat():
    editor = Editor([_view(14)])
    editor.answer = lambda body: (202, "application/json", json.dumps(
        {"queued": True, "id": "q1", "position": 1, "note": "queued - it goes as its own message the moment this turn ends"}))
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.click("#listTalk")
        _type(page, "Where are we?")
        _until(page, lambda: "busy with another job" in page.inner_text("#editorState"))
        assert page.inner_text("#editorState") == (
            "The editor is busy with another job. Your comment goes to it the moment that job ends, "
            "and the answer shows here.")
        assert re.search(r"You\s*Where are we\?", page.inner_text("#editorLog"))
        _shot(page, "queued", "editorState", "editorLog", "editorText")
        # Its turn runs and answers: the row is his message as sent, with the editor's reply.
        sent = editor.messages[0]["text"]
        editor.turns.append({"run_id": "r9", "at": _at(-2), "from": "ziv", "transport": "api", "origin": "you",
                             "message": sent, "ack": "", "result": "Episode 14 waits on your layout note."})
        _until(page, lambda: "waits on your layout note" in page.inner_text("#editorLog"), 12000)
        assert page.inner_text("#editorState") == READY
        assert page.evaluate("window.__voice.starts.length") == 0
        browser.close()


def test_a_stream_that_drops_after_it_was_taken_is_answered_from_the_chat():
    editor = Editor([_view(14)])
    editor.answer = lambda body: (200, "text/event-stream", _sse(
        ("accepted", {"agent": "book-editor", "request": "ab12cd34"}),
        ("first", {"text": "Looking now.", "smart": True})))
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.click("#listTalk")
        _type(page, "Where are we?")
        _until(page, lambda: "dropped while it was answering" in page.inner_text("#editorState"))
        sent = editor.messages[0]["text"]
        editor.turns.append({"run_id": "r9", "at": _at(-2), "from": "ziv", "transport": "api", "origin": "you",
                             "message": sent + "\n\n(a note KM BOT adds at the end)", "ack": "Looking now.",
                             "result": "Two episodes wait on you."})
        _until(page, lambda: "Two episodes wait on you." in page.inner_text("#editorLog"), 12000)
        # Each line once: the instant line was already shown from the stream.
        assert page.inner_text("#editorLog").count("Looking now.") == 1
        browser.close()


def test_signed_out_of_km_bot_nothing_is_fetched_behind_the_page_and_the_comment_keeps_its_draft():
    editor = Editor([_view(14)])
    editor.signed_in = False
    with sync_playwright() as pw:
        browser, page = _open(pw, editor)
        page.wait_for_timeout(2500)
        assert editor.count("VOICE") == 0  # no probe that could raise a sign-in box
        page.click("#listTalk")
        _type(page, "Where are we?")
        _until(page, lambda: page.locator("#editorSignin").is_visible())
        assert page.inner_text("#editorState") == "Sign in to KM BOT on this phone once, then come back and tap the icon again."
        assert page.input_value("#editorText") == "Where are we?"
        assert "Where are we?" not in page.inner_text("#editorLog")
        browser.close()


def test_km_bot_is_read_while_the_book_opens_not_after():
    editor = Editor([_view(14)])
    editor.hold_list = True
    with sync_playwright() as pw:
        browser, page = _open(pw, editor, wait=False)
        _until(page, lambda: editor.held)
        _until(page, lambda: editor.count("KMBOT", "/kmbot-api/history") == 1)
        assert editor.count("KMBOT", "/kmbot-api/tasks") == 1  # both while the chapters are still out
        editor.hold_list = False
        editor(editor.held.pop())
        page.locator("#agentCatchup").wait_for()
        assert "Writing episode 15" in page.inner_text("#agentCatchup")
        browser.close()
