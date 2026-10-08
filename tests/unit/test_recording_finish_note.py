"""Finish at phone width: one press, the note, then the list with live progress. Synthetic data.

8-Oct call (T-10568): "show me a modal for three seconds about what is going to
be done in the background and then move me to the next phase." And (T-10566):
"I don't even need to see the finish button after I clicked on it already."
"""

from __future__ import annotations

import os
import time

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record, _studio_page

pytest.importorskip("playwright.sync_api")

SESSION_FINISH = "() => window.__sessionFinishes || 0"
COUNT_FINISHES = """
(() => {
  const real = window.fetch;
  window.__sessionFinishes = 0;
  window.fetch = function (url, options) {
    if (String(url).includes('/recording-sessions/') && String(url).endsWith('/finish')) window.__sessionFinishes += 1;
    return real.apply(this, arguments);
  };
})();
"""


def test_one_finish_press_shows_the_note_then_the_list_with_progress(studio, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    from tce.api.routers import production as prod

    # The edit itself is not this test's subject: the video stays "saved", so the
    # card's last step is the one waiting for the edit to start.
    monkeypatch.setattr(prod.settings, "production_auto_edit", False)

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, COUNT_FINISHES)
        assert page.viewport_size["width"] <= 430, "measured at phone width"
        _record(page, 3)
        pressed = time.monotonic()
        # The press, and an impatient second tap 200 ms later, as on 8-Oct.
        page.evaluate(
            "() => { const b = document.getElementById('finishSessionButton'); b.click();"
            " setTimeout(() => b.click(), 200); }"
        )
        page.wait_for_function("() => document.getElementById('finishDialog').open", timeout=5000)
        assert page.evaluate("() => document.getElementById('finishSessionButton').hidden"), "Finish goes on the first press"
        steps = page.evaluate("() => [...document.querySelectorAll('#finishDialogSteps li')].map(li => li.textContent)")
        assert steps == [
            "Sending the last clip from this phone",
            "Putting the clips together and checking the sound",
            "Editing the video",
        ]
        assert page.evaluate("() => document.getElementById('finishDialogNow').textContent.trim().length") > 0
        shots = os.environ.get("TCE_SHOTS")
        if shots:
            page.screenshot(path=f"{shots}/finish-note.png")

        page.wait_for_selector("#queueView:not([hidden])", timeout=90000)
        shown_for = time.monotonic() - pressed
        assert not page.evaluate("() => document.getElementById('finishDialog').open")
        assert shown_for >= 2.9, f"the note was up for only {shown_for:.1f}s"
        assert page.evaluate(SESSION_FINISH) == 1, "the second tap must not send a second Finish"

        card = page.wait_for_selector("#finishStatus:not([hidden])", timeout=5000)
        box = card.bounding_box()
        assert box and box["width"] <= page.viewport_size["width"], "the card fits the phone"
        # The build ends while he is on the list; the card follows it without a reload.
        page.wait_for_function(
            "() => document.getElementById('finishStatusNow').textContent"
            " === 'Saved as one video. The edit starts in a moment.'",
            timeout=60000,
        )
        states = page.evaluate("() => [...document.querySelectorAll('#finishStatusSteps li')].map(li => li.className)")
        assert states == ["done", "done", "now"], states
        assert page.evaluate("() => !document.getElementById('finishOpen').hidden")
        assert page.evaluate(SESSION_FINISH) == 1
        if shots:
            page.screenshot(path=f"{shots}/finish-card.png")
        context.close()
        browser.close()
