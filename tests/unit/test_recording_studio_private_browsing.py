"""A phone that will not keep the recorded pieces: Safari in a private tab. Synthetic data.

26-Oct (Angel's QA of Connie's video app, iPhone Safari, private tab): Record started,
not one piece reached the server in five minutes, and after Pause every button was
dead: Record stayed greyed, Pause and Stop did nothing. Each piece was stored on the
phone BEFORE it was sent; the private tab refused the store, so nothing was sent, and
Stop died waiting on the refused store. Reproduced the same day on a real iPhone 14
(iOS 26.5) in a private tab: 0 chunks, the same dead bar. A normal tab sent 15.
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record, _studio_page

pytest.importorskip("playwright.sync_api")

# What the private tab did: the phone's store refuses a recorded piece.
REFUSES_PIECES = """
const realPut = IDBObjectStore.prototype.put;
IDBObjectStore.prototype.put = function (value, ...rest) {
  if (value && value.blob instanceof Blob) {
    throw new DOMException('Error preparing Blob/File data to be stored in object store', 'UnknownError');
  }
  return realPut.call(this, value, ...rest);
};
"""

# The other way a phone's store fails: it never answers at all.
NEVER_ANSWERS = """
const realOpen = indexedDB.open.bind(indexedDB);
indexedDB.open = function (name, version) {
  if (name === 'tce-recording-v1') return {};
  return realOpen(name, version);
};
"""


@pytest.mark.parametrize("store", [REFUSES_PIECES, NEVER_ANSWERS], ids=["refuses-pieces", "never-answers"])
def test_a_phone_that_will_not_keep_pieces_still_sends_them_and_stop_saves_the_take(studio, store):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, store)
        sent = []
        page.on("request", lambda r: sent.append(r.url) if r.method == "PUT" and "/chunks/" in r.url else None)
        _record(page, 10)
        assert sent, "not one recorded piece was sent while recording"
        # Her steps: Pause, Resume, Pause again, then Stop.
        with page.expect_response(
            lambda r: "/recording-clips/" in r.url and r.url.endswith("/finish"), timeout=30000
        ) as saved:
            page.click("#pauseButton")
            page.wait_for_timeout(1000)
            page.click("#pauseButton")
            page.wait_for_timeout(1500)
            page.click("#pauseButton")
            page.wait_for_timeout(500)
            page.click("#finishClipButton")
        assert saved.value.ok, f"the take was not saved: {saved.value.status} {saved.value.text()[:200]}"
        page.wait_for_function("() => !document.getElementById('recordButton').disabled", timeout=15000)
        assert page.inner_text("#pauseButton").strip() == "Pause", "a stopped take left the button saying Resume"
        context.close()
        browser.close()
