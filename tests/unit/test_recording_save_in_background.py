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


def test_leaving_right_after_finish_still_sends_the_take_for_editing(studio, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard

    # Today is the page he goes back to. Off, it bounces to the studio instead.
    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)

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
        # And Today says so, in a line that pushes the page down rather than covering it.
        page.wait_for_function(
            "() => (document.getElementById('tceSavingBar')?.textContent || '')"
            ".startsWith('Your take is saved and on its way to editing.')",
            timeout=10000,
        )
        bar = page.evaluate(
            "() => { const b = document.getElementById('tceSavingBar');"
            " return { position: getComputedStyle(b).position, after: b.previousElementSibling?.tagName }; }"
        )
        assert bar == {"position": "static", "after": "HEADER"}, bar
        assert page.evaluate("() => localStorage.getItem('tce-recording-pending')") == '{"clips":{},"sessions":{}}'
        context.close()
        browser.close()


def test_the_finish_note_goes_on_one_tap(studio):  # noqa: F811
    """The three-second note stays (8-Oct, his ask), but it never holds him."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, SLOW_CLIP_FINISH)
        _record(page, 3)
        page.evaluate("() => { window.__slowFinish = 4000; }")
        page.click("#finishSessionButton")
        page.wait_for_function("() => document.getElementById('finishDialog').open", timeout=5000)
        assert "You can leave this page" in page.inner_text("#finishDialogNow")
        page.click("#finishDialog")
        page.wait_for_function("() => !document.getElementById('finishDialog').open", timeout=500)
        page.wait_for_selector("#queueView:not([hidden])", timeout=2000)
        # The end of the clip is still on its way, and the list says so without a wall.
        assert "You can leave this page" in page.inner_text("#finishStatusNow")
        with context.expect_event(
            "request", lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"), timeout=30000
        ):
            pass
        context.close()
        browser.close()
