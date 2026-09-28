"""The recording timer starts every take, and every script, from zero. Synthetic data.

28-Sep call: after a nine-minute take and "start editing", the next script
opened with the timer still reading nine minutes. Stop cleared the interval but
never the number on screen, so it stayed until the next take's first tick. The
video never carried over (a new take set per script, a new clip per take); the
clock did.
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record, _studio_page

pytest.importorskip("playwright.sync_api")

TIMER = "() => ({ text: document.getElementById('timer').textContent, hidden: document.getElementById('timer').hidden })"


def test_the_next_take_and_the_next_script_start_the_clock_at_zero(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        _record(page, 3)
        with page.expect_response(lambda r: "/finish" in r.url and "recording-clips" in r.url, timeout=60000):
            page.click("#finishClipButton")
        assert page.evaluate(TIMER)["text"] != "00:00", "the stopped take shows how long it was"

        # The next take: zero from the first moment, not the last take's length.
        page.wait_for_function("() => !document.getElementById('recordButton').disabled", timeout=60000)
        first = page.evaluate("() => { document.getElementById('recordButton').click();"
                              " return document.getElementById('timer').textContent; }")
        page.wait_for_function(
            "() => document.getElementById('studioView').classList.contains('is-recording')", timeout=30000
        )
        started = page.evaluate(TIMER)
        assert started["text"] in ("00:00", "00:01"), f"the new take started at {started['text']} (first read {first})"
        page.wait_for_timeout(1500)
        with page.expect_response(lambda r: "/finish" in r.url and "recording-clips" in r.url, timeout=60000):
            page.click("#finishClipButton")

        # Send for editing: back on the list, the clock is gone and zero.
        with page.expect_response(
            lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"), timeout=90000
        ):
            page.click("#finishSessionButton")
        page.wait_for_selector("#queueView:not([hidden])")
        after = page.evaluate(TIMER)
        assert after == {"text": "00:00", "hidden": True}, f"after sending for editing the timer read {after}"
        context.close()
        browser.close()
