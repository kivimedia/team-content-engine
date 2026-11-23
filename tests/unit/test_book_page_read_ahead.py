"""The Book reads the next paragraphs ahead while one plays (23-Nov, wait-less item F10).

Only audio the server already holds is read ahead (?cached=1, answered 204 for a paragraph
not made yet), so a paragraph never narrated is asked for exactly when its turn comes, as
before, and nothing is bought ahead of him. Pause stops the reads still on their way, and a
new chapter lets go of every one read ahead. The stubbed server is test_book_page_wait_less.py's,
with the audio route added. No visible change, so no pictures.
"""

from __future__ import annotations

import io
import re
import wave
from urllib.parse import urlsplit

from tests.unit.test_book_page_wait_less import READY_16, Book, _until, _view, sync_playwright


def _wav(ms: int) -> bytes:
    """A short silent clip the browser plays to its end."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * (8 * ms))
    return out.getvalue()


SHORT = _wav(300)
LONG = _wav(4000)
FOUR = {**READY_16, "paragraphs": ["First paragraph.", "Second paragraph.", "Third paragraph.", "Fourth paragraph."],
        "narration": {"on": True, "voice_name": "Brian"}}

URLS = """
window.__urls = { made: [], revoked: [] };
const make = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
URL.createObjectURL = (b) => { const u = make(b); window.__urls.made.push(u); return u; };
URL.revokeObjectURL = (u) => { window.__urls.revoked.push(u); return revoke(u); };
"""


class Reading(Book):
    """The Book's stub with the paragraph audio: `made` is what the server already holds."""

    def __init__(self, views, made=(), first=SHORT):
        super().__init__(views)
        self.made = set(made)
        self.first = first
        self.audio: list = []
        self.hold_ahead = False
        self.held: list = []

    def __call__(self, route):
        parts = urlsplit(route.request.url)
        found = re.fullmatch(r"/api/v1/book/chapters/(\d+)/audio/(\d+)", parts.path)
        if not found:
            return super().__call__(route)
        i = int(found.group(2))
        if "cached=1" in parts.query:
            self.audio.append(("AHEAD", i))
            if self.hold_ahead:
                self.held.append(route)
                return None
            if i in self.made:
                return route.fulfill(body=SHORT, content_type="audio/wav")
            return route.fulfill(status=204, headers={"Cache-Control": "no-store"}, body="")
        self.audio.append(("AUDIO", i))  # the ask that may buy it, as today
        self.made.add(i)
        return route.fulfill(body=self.first if i == 0 else SHORT, content_type="audio/wav")

    def asked(self, kind):
        return [i for k, i in self.audio if k == kind]


def _open(pw, book, path):
    browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    page.add_init_script(URLS)
    page.route("https://book.test/**", book)
    page.goto(f"https://book.test{path}")
    page.locator("#playButton").wait_for()
    return browser, page


def test_the_next_paragraphs_play_from_what_was_read_ahead_and_nothing_is_bought_ahead():
    book = Reading([_view(16, **FOUR)], made={1, 2})
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book/16")
        page.click("#playButton")
        _until(page, lambda: "End of the chapter" in page.inner_text("#bookState"), 20000)
        # Paragraphs 2 and 3 were already made: they played from the read ahead, never asked for
        # again. Paragraph 4 was not made: read ahead as "not made yet", then asked for in its turn.
        assert book.asked("AUDIO") == [0, 3]
        assert book.asked("AHEAD") == [1, 2, 3]
        assert page.evaluate("window.__urls.made.length") == 4
        browser.close()


def test_pause_stops_the_reads_on_their_way_and_nothing_more_is_asked_for():
    book = Reading([_view(16, **FOUR)], made={1, 2}, first=LONG)
    book.hold_ahead = True
    failed: list = []
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book/16")
        page.on("requestfailed", lambda r: failed.append(r.url) if "cached=1" in r.url else None)
        page.click("#playButton")
        _until(page, lambda: len(book.held) == 2)
        page.click("#playButton")  # Pause, while the first paragraph plays
        _until(page, lambda: len(failed) == 2, 5000)
        page.wait_for_timeout(800)
        assert book.asked("AUDIO") == [0] and book.asked("AHEAD") == [1, 2]
        assert "Paused" in page.inner_text("#bookState")
        browser.close()


def test_a_new_chapter_lets_go_of_every_paragraph_read_ahead():
    book = Reading([_view(16, **FOUR, next=17), _view(17, **{**FOUR, "previous": 16})], made={1, 2}, first=LONG)
    with sync_playwright() as pw:
        browser, page = _open(pw, book, "/book/16")
        page.click("#playButton")
        _until(page, lambda: page.evaluate("window.__urls.made.length") == 3)  # paragraph 1, and 2 and 3 read ahead
        page.click("#nextChapter")
        page.wait_for_function("document.getElementById('chapterTitle').textContent.startsWith('Episode 17')")
        made, revoked = page.evaluate("[window.__urls.made, window.__urls.revoked]")
        # Both read ahead are let go; only the paragraph that was playing is still held by the
        # player, and it goes when the next one plays, as before.
        assert set(made[1:]) <= set(revoked), (made, revoked)
        assert book.asked("AUDIO") == [0]
        browser.close()
