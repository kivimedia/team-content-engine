"""Record without a script waits less (23-Nov, wait-less item B9, the page side).

Parts in flight two or three at a time, never more, and the finish only once every part
has its answer; Done answered at once by a finish TCE puts together in the background,
the page asking how it ended; and an older TCE that answers with the video still works.
A stubbed server in the browser (no camera needed: the parts are put on the phone's
store the way a take leaves them). Pictures of each state go to TCE_SHOT_DIR when set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
ASSETS = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"
SHOTS = os.environ.get("TCE_SHOT_DIR")
TALK = "talk-1"
FINISHING = {"talk_id": TALK, "state": "finishing", "status": "finishing", "upload_id": None, "edit": True,
             "choice_kept": False, "detail": "Your recording is being put together into its video now."}
RESULT = {"talk_id": TALK, "upload_id": "video-1", "title": "Recording, 23 Nov", "status": "uploaded",
          "edit_started": True, "already_finished": False, "choice_kept": False, "missing_pieces": [],
          "edit": True, "archived": False, "detail": "Your recording, joined."}
REFUSED = "The pieces could not be joined into a video that plays (mp4: no sound)"
NEVER_EARLY = ("saved", "sent", "in your library")

SEED = """(count) => new Promise((resolve, reject) => {
  const open = indexedDB.open('tce-solo-v1', 1);
  open.onupgradeneeded = () => {
    open.result.createObjectStore('pieces', { keyPath: 'key' });
    open.result.createObjectStore('takes', { keyPath: 'talkId' });
  };
  open.onerror = () => reject(open.error);
  open.onsuccess = () => {
    const tx = open.result.transaction(['pieces', 'takes'], 'readwrite');
    for (let i = 0; i < count; i += 1) {
      tx.objectStore('pieces').put({ key: 'talk-1:' + i, talkId: 'talk-1', sequence: i,
        blob: new Blob(['piece ' + i], { type: 'video/mp4' }), at: i + 1 });
    }
    tx.objectStore('takes').put({ talkId: 'talk-1', done: true, startedAt: '2026-11-23T08:00:00Z',
      endedAt: '2026-11-23T08:01:00Z', durationMs: 60000 });
    tx.oncomplete = () => { open.result.close(); resolve(); };
    tx.onerror = () => reject(tx.error);
  };
})"""

LEFT = """() => new Promise((resolve) => {
  const open = indexedDB.open('tce-solo-v1', 1);
  open.onsuccess = () => {
    const tx = open.result.transaction(['pieces', 'takes'], 'readonly');
    const p = tx.objectStore('pieces').count();
    const t = tx.objectStore('takes').count();
    tx.oncomplete = () => { open.result.close(); resolve([p.result, t.result]); };
  };
})"""


class Server:
    """The TCE routes the page calls, answered in the browser. Parts can be held open."""

    def __init__(self, finish=None, hold_parts=False):
        self.finish = finish or (lambda: (202, FINISHING))
        self.talk = lambda: {"talk_id": TALK, "status": "finishing", "finish": {"state": "finishing"}}
        self.hold_parts = hold_parts
        self.open_parts: list = []
        self.calls: list = []
        self.most_at_once = 0

    def __call__(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/record/solo":
            return route.fulfill(path=ASSETS / "recording-solo.html", content_type="text/html")
        if path in {"/recording.css", "/recording-solo.js", "/take-reward.js"}:
            return route.fulfill(path=ASSETS / path[1:])
        if "/chunks/" in path:
            self.calls.append(("PUT", int(path.rsplit("/", 1)[1])))
            if self.hold_parts:
                self.open_parts.append(route)
                self.most_at_once = max(self.most_at_once, len(self.open_parts))
                return None
            return route.fulfill(json={"ok": True})
        if path.endswith("/finish"):
            self.calls.append(("FINISH", json.loads(request.post_data or "{}")))
            status, body = self.finish()
            return route.fulfill(status=status, json=body)
        if path.endswith(f"/agent-talks/{TALK}") and request.method == "GET":
            self.calls.append(("GET", None))
            return route.fulfill(json=self.talk())
        return route.fulfill(json={})

    def answer_part(self, status=200):
        route = self.open_parts.pop(0)
        route.fulfill(status=status, json={"ok": True} if status == 200 else {"detail": "Server busy"})

    def kinds(self):
        return [c[0] for c in self.calls]


def _until(page, check, ms=15000):
    for _ in range(ms // 50):
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError("never happened")


def _page(pw, server):
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.route("https://studio.test/**", server)
    page.goto("https://studio.test/record/solo")
    return browser, page


def _shot(page, name):
    if not SHOTS:
        return
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, width)
        page.screenshot(path=str(Path(SHOTS) / f"solo-{name}-{width}.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})


def _line(page):
    return (page.inner_text("#soloStatus") + " " + page.inner_text("#soloState")).strip()


def test_done_answers_at_once_and_the_page_reads_how_the_finish_ended():
    server = Server()
    with sync_playwright() as pw:
        browser, page = _page(pw, server)
        page.evaluate(SEED, 1)
        page.reload()
        _until(page, lambda: "FINISH" in server.kinds())
        assert server.calls[-1][1] == {"ended_at": "2026-11-23T08:01:00Z", "duration_ms": 60000, "edit": True,
                                       "background": True}
        _until(page, lambda: "being put together" in _line(page))
        assert page.inner_text("#soloState") == "Putting it together"
        assert page.inner_text("#soloStatus") == (
            "Your recording is being put together into its video now. You can leave this page.")
        # While TCE holds it nothing says it is saved, sent or in the Library.
        assert not any(word in _line(page).lower() for word in NEVER_EARLY)
        _until(page, lambda: server.kinds().count("GET") >= 1, 8000)
        assert server.kinds().count("FINISH") == 1  # it is read, never finished again
        _shot(page, "finishing")
        server.talk = lambda: {"talk_id": TALK, "status": "finished", "upload_id": "video-1",
                               "finish": {"state": "finished", "result": RESULT}}
        _until(page, lambda: "In your Library" in _line(page), 10000)
        # Exactly what a finish has always shown.
        assert page.inner_text("#soloState") == "Sent"
        assert page.inner_text("#soloStatus").startswith('In your Library as "Recording, 23 Nov". Jennifer is editing it now.')
        assert page.evaluate(LEFT) == [0, 0]
        _shot(page, "finished")
        browser.close()


def test_a_refused_join_shows_the_refusal_as_before_and_is_tried_again():
    server = Server()
    server.talk = lambda: {"talk_id": TALK, "status": "failed",
                           "finish": {"state": "failed", "error": {"status": 422, "detail": REFUSED}}}
    with sync_playwright() as pw:
        browser, page = _page(pw, server)
        page.evaluate(SEED, 1)
        page.reload()
        _until(page, lambda: "could not be finished" in _line(page), 12000)
        assert page.inner_text("#soloStatus") == (
            f"Sent, but it could not be finished yet ({REFUSED}). Trying again in a few seconds.")
        assert page.evaluate(LEFT) == [0, 1]  # the take stays on the phone
        _shot(page, "refused")
        _until(page, lambda: server.kinds().count("FINISH") == 2, 12000)
        browser.close()


def test_an_older_tce_that_answers_with_the_video_works_as_before():
    server = Server(finish=lambda: (200, {**RESULT, "status": "uploaded"}))
    with sync_playwright() as pw:
        browser, page = _page(pw, server)
        page.evaluate(SEED, 1)
        page.reload()
        _until(page, lambda: "In your Library" in _line(page))
        assert "GET" not in server.kinds() and page.evaluate(LEFT) == [0, 0]
        browser.close()

