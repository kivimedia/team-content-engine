"""Leaving the studio while a take is still saving. Synthetic data.

12-Oct, Ziv on a call: "I need the saving process to be in the background and not
force me to stay on that page. Like if I click back to go back to TCE ... I don't
want to wait until you save ... move the files with you to another page, continue
with the saving."

So: Stop, Finish, and leave at once for another TCE page. The end of the clip and
the hand-over for editing must still happen, from the page he went to.
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import (
    LANDSCAPE_CAMERA,
    SLOW_CLIP_FINISH,
    _record,
    _studio_page,
)

pytest.importorskip("playwright.sync_api")


def test_leaving_right_after_finish_still_sends_the_take_for_editing(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, SLOW_CLIP_FINISH)
        _record(page, 4)
        # The end of the clip is still on its way, like a long take on a walk.
        page.evaluate("() => { window.__slowFinish = 4000; }")
        page.evaluate(
            "() => { document.getElementById('finishClipButton').click();"
            " setTimeout(() => document.getElementById('finishSessionButton').click(), 300); }"
        )
        page.wait_for_timeout(800)
        # He leaves at once. Nothing on the studio is allowed to hold him.
        page.evaluate("() => { window.__slowFinish = 0; }")
        with context.expect_event(
            "request",
            lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"),
            timeout=30000,
        ) as finished:
            page.goto(f"{studio['base']}/today")
        assert len(finished.value.post_data_json["selected_clip_ids"]) == 1
        context.close()
        browser.close()
