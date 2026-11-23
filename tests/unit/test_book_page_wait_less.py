"""The Book page waits less when a filmed session ends (23-Nov, wait-less item B9).

Its finish is put together in the background: the page says so at once and asks how it
ended, then shows what it always showed (part 2). Its parts go two or three at a time,
never more, and the finish waits for every one (part 3). The stubbed server here is shared
with test_book_page_fast_clicks.py. Pictures of each state go to TCE_SHOT_DIR when set.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
ASSETS = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
SHOTS = os.environ.get("TCE_SHOT_DIR")
TALK = "talk-b1"
TITLE = "Book session on Episode 16, 23 Nov"
REFUSED = "The pieces could not be joined into a video that plays (mp4: no sound)"


def _view(n, **over):
    """A chapter as GET /book/chapters/{n} draws it."""
    view = {"n": n, "title": f"Episode title {n}", "part": "Part two", "group": "new", "version": 1,
            "status": "draft", "status_words": "Draft", "paragraphs": [], "held_paragraphs": 0,
            "previous": None, "next": None, "narration": {"on": False}, "editor_seat": "tce",
            "phased": True, "readable": False, "phase": "layout", "phase_words": "Layout to approve",
            "layout_status": "proposed", "write_requested_at": None, "layout_approved_at": None,
            "layout": {"big_idea": f"The big idea of episode {n}", "covers": ["A concrete story", "What to try"],
                       "question": ""},
            "layout_notes": [], "layout_items": [], "layout_text": "", "outline": ""}
    view.update(over)
    return view


READY_16 = {"phase": "ready", "phase_words": "Ready to listen", "readable": True, "status": "in_review",
            "status_words": "In review", "layout_status": "approved",
            "paragraphs": ["First paragraph.", "Second paragraph.", "Third paragraph."]}


def _summary(view):
    keys = ("n", "title", "part", "group", "version", "status", "status_words", "phased", "readable", "phase",
            "phase_words", "layout_status", "write_requested_at")
    return {**{k: view[k] for k in keys}, "paragraphs": len(view["paragraphs"]), "minutes": 1 if view["readable"] else 0,
            "big_idea": view["layout"]["big_idea"], "layout_items": [], "layout_text": ""}


class Book:
    def __init__(self, views):
        self.views = {v["n"]: v for v in views}
        self.calls: list = []
        self.finish = lambda: (202, {"talk_id": TALK, "state": "finishing", "status": "finishing", "upload_id": None,
                                     "edit": True, "choice_kept": False, "detail": "Your book session is being put together."})
        self.talk = lambda: {"talk_id": TALK, "status": "finishing", "finish": {"state": "finishing"}}
        self.hold_parts = False
        self.open_parts: list = []
        self.most_at_once = 0

    def __call__(self, route):
        request = route.request
        path = urlsplit(request.url).path
        method = request.method
        if path == "/blank":  # the same site, without the page: a session is put there first
            return route.fulfill(body="<!doctype html><title>blank</title>", content_type="text/html")
        if path == "/book" or re.fullmatch(r"/book/\d+", path):
            return route.fulfill(path=ASSETS / "book.html", content_type="text/html")
        if path in {"/book.js", "/book.css", "/take-reward.js"}:
            return route.fulfill(path=ASSETS / path[1:])
        if path == "/api/v1/book/chapters":
            self.calls.append(("LIST", None))
            return route.fulfill(json={"chapters": [_summary(v) for v in self.views.values()], "narration": {"on": False}})
        found = re.fullmatch(r"/api/v1/book/chapters/(\d+)(?:/(\w+))?", path)
        if found:
            n, action = int(found.group(1)), found.group(2)
            if action is None:
                self.calls.append(("GET", n))
                return route.fulfill(json=self.views[n])
            body = json.loads(request.post_data or "{}")
            self.calls.append((action.upper(), n))
            view = self.views[n]
            if action == "layout":
                view.update(layout_status="approved", phase="approved_unwritten", phase_words="Layout approved, not written",
                            layout_approved_at="2026-11-23T08:00:00")
                return route.fulfill(json={"n": n, "action": body["action"], "result": {}, "phase": view["phase"],
                                           "phase_words": view["phase_words"], "chapter": view})
            if action == "write":
                view.update(write_requested_at="2026-11-23T08:05:00")
                return route.fulfill(json={"n": n, "write_requested_at": view["write_requested_at"], "already": False,
                                           "chapter": view})
            if action == "status":
                approved = body["status"] == "approved"
                view.update(status=body["status"], status_words="Approved" if approved else "In review",
                            phase="approved" if approved else "ready")
                return route.fulfill(json={"n": n, "status": view["status"], "status_words": view["status_words"],
                                           "at": "2026-11-23T08:10:00", "chapter": view})
        if "/agent-talks/" in path and "/chunks/" in path:
            self.calls.append(("PUT", int(path.rsplit("/", 1)[1])))
            if self.hold_parts:
                self.open_parts.append(route)
                self.most_at_once = max(self.most_at_once, len(self.open_parts))
                return None
            return route.fulfill(json={"ok": True})
        if path.endswith(f"/agent-talks/{TALK}/finish"):
            self.calls.append(("FINISH", json.loads(request.post_data or "{}")))
            status, answer = self.finish()
            return route.fulfill(status=status, json=answer)
        if path.endswith(f"/agent-talks/{TALK}") and method == "GET":
            self.calls.append(("TALK", None))
            return route.fulfill(json=self.talk())
        return route.fulfill(status=404, json={"detail": "not in this test"})

    def kinds(self):
        return [c[0] for c in self.calls]


def _until(page, check, ms=15000):
    for _ in range(ms // 50):
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError("never happened")


def _open(pw, book, path, parts=0):
    """The page; with `parts`, a filmed session (that many parts and its Send) is on the phone
    first, put there from a blank page of the same site, so only this page sends it."""
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.route("https://book.test/**", book)
    if parts:
        page.goto("https://book.test/blank")
        page.evaluate(SEED, [parts, TALK, TITLE])
    page.goto(f"https://book.test{path}")
    return browser, page


def _shot(page, name, *ids):
    """A picture at phone and desktop width; the named controls fit and never overlap."""
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        page.wait_for_timeout(100)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, width)
        boxes = [page.locator(f"#{i}").bounding_box() for i in ids]
        for i, box in zip(ids, boxes, strict=True):
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (name, width, i, box)
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                one, two = boxes[a], boxes[b]
                apart = (one["x"] + one["width"] <= two["x"] or two["x"] + two["width"] <= one["x"]
                         or one["y"] + one["height"] <= two["y"] or two["y"] + two["height"] <= one["y"])
                assert apart, (name, width, ids[a], ids[b])
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(SHOTS) / f"book-{name}-{width}.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})


SEED = """([count, talk, title]) => new Promise((resolve, reject) => {
  const open = indexedDB.open('tce-book-v1', 1);
  open.onupgradeneeded = () => {
    open.result.createObjectStore('pieces', { keyPath: 'key' });
    open.result.createObjectStore('takes', { keyPath: 'talkId' });
  };
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const tx = open.result.transaction(['pieces', 'takes'], 'readwrite');
    for (let i = 0; i < count; i += 1) {
      tx.objectStore('pieces').put({ key: talk + ':' + i, talkId: talk, sequence: i,
        blob: new Blob(['piece ' + i], { type: 'video/mp4' }), at: i + 1 });
    }
    tx.objectStore('takes').put({ talkId: talk, title, done: true, choice: 'send', lines: [],
      startedAt: '2026-11-23T08:00:00Z', endedAt: '2026-11-23T08:04:00Z', durationMs: 240000 });
    tx.oncomplete = () => { open.result.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  };
})"""

TAKES_LEFT = """() => new Promise((resolve) => {
  const open = indexedDB.open('tce-book-v1', 1);
  open.onsuccess = () => {
    const tx = open.result.transaction(['takes'], 'readonly');
    const t = tx.objectStore('takes').count();
    tx.oncomplete = () => { open.result.close(); resolve(t.result); };
  };
})"""


def test_a_session_is_put_together_in_the_background_and_then_says_what_it_always_said():
    book = Book([_view(14), _view(16, **READY_16)])
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book", parts=2)
        _until(page, lambda: "FINISH" in book.kinds())
        assert book.kinds()[:book.kinds().index("FINISH")].count("PUT") == 2
        assert book.calls[-1][1] == {"ended_at": "2026-11-23T08:04:00Z", "duration_ms": 240000, "transcript": [],
                                     "edit": True, "background": True}
        _until(page, lambda: "being put together" in page.inner_text("#bookStatus"))
        assert page.inner_text("#bookStatus") == (
            f'"{TITLE}" is being put together into its video now. You can leave this page.')
        assert "saved" not in (page.get_attribute("#bookStatus", "class") or "")
        assert "saved" not in page.inner_text("#bookStatus").lower()
        _until(page, lambda: "TALK" in book.kinds(), 8000)
        assert book.kinds().count("FINISH") == 1
        _shot(page, "finishing", "bookStatus")
        book.talk = lambda: {"talk_id": TALK, "status": "finished", "upload_id": "video-9", "finish": {
            "state": "finished", "result": {"upload_id": "video-9", "status": "uploaded", "talk_id": TALK, "title": TITLE,
                                            "missing_pieces": [], "edit": True, "archived": False, "edit_started": True,
                                            "already_finished": False, "choice_kept": False}}}
        _until(page, lambda: "Saved in your Library" in page.inner_text("#bookStatus"), 10000)
        # What a finish has always shown, drawn as good news.
        assert page.inner_text("#bookStatus") == f'Saved in your Library: "{TITLE}". Jennifer is editing it.'
        assert "saved" in page.get_attribute("#bookStatus", "class")
        assert page.evaluate(TAKES_LEFT) == 0
        _shot(page, "saved", "bookStatus")
        browser.close()


def test_three_parts_at_once_never_more_and_the_finish_waits_for_every_one():
    book = Book([_view(14)])
    book.hold_parts = True
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book", parts=5)
        _until(page, lambda: len(book.open_parts) == 3)
        page.wait_for_timeout(400)
        assert len(book.open_parts) == 3 and book.kinds().count("PUT") == 3  # never a fourth
        assert sorted(c[1] for c in book.calls if c[0] == "PUT") == [0, 1, 2]  # oldest first
        while True:  # the finish comes only once the last part has its answer
            _until(page, lambda: book.open_parts or "FINISH" in book.kinds())
            if "FINISH" in book.kinds():
                break
            assert len(book.open_parts) <= 3
            book.open_parts.pop(0).fulfill(json={"ok": True})
        assert not book.open_parts and book.kinds()[:book.kinds().index("FINISH")].count("PUT") == 5
        assert book.most_at_once == 3 and book.kinds().count("PUT") == 5
        browser.close()


def test_a_refused_join_pauses_the_session_as_before():
    book = Book([_view(14)])
    book.talk = lambda: {"talk_id": TALK, "status": "failed",
                         "finish": {"state": "failed", "error": {"status": 422, "detail": REFUSED}}}
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book", parts=1)
        _until(page, lambda: "Sending paused" in page.inner_text("#bookStatus"), 12000)
        assert page.inner_text("#bookStatus") == (
            f"Sending paused ({REFUSED}). Trying again in a few seconds; nothing is lost.")
        assert page.evaluate(TAKES_LEFT) == 1
        _until(page, lambda: book.kinds().count("FINISH") == 2, 12000)
        browser.close()


def test_a_server_error_behind_the_answer_is_tried_again_and_never_reads_as_a_refusal():
    """A 5xx in the finish's end (the join itself crashed) is what a 5xx from the finish has
    always been: paused and tried again. Only a 422 is a video that could not be made."""
    book = Book([_view(14)])
    book.talk = lambda: {"talk_id": TALK, "status": "failed", "finish": {"state": "failed", "error": {
        "status": 500, "detail": "Your book session could not be put together just now: the server ran into an error."}}}
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book", parts=1)
        _until(page, lambda: "Sending paused" in page.inner_text("#bookStatus"), 12000)
        assert page.inner_text("#bookStatus") == ("Sending paused (the server could not put it together just now). "
                                                  "Trying again in a few seconds; nothing is lost.")
        assert page.evaluate(TAKES_LEFT) == 1
        _shot(page, "server-error", "bookStatus")
        _until(page, lambda: book.kinds().count("FINISH") == 2, 12000)
        browser.close()


def test_an_older_tce_that_answers_with_the_video_works_as_before():
    book = Book([_view(14)])
    book.finish = lambda: (200, {"upload_id": "video-9", "status": "uploaded", "talk_id": TALK, "title": TITLE,
                                 "missing_pieces": [], "edit": True, "archived": False, "edit_started": True,
                                 "already_finished": False, "choice_kept": False})
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book", parts=2)
        _until(page, lambda: "Saved in your Library" in page.inner_text("#bookStatus"))
        assert "TALK" not in book.kinds() and page.evaluate(TAKES_LEFT) == 0
        browser.close()
