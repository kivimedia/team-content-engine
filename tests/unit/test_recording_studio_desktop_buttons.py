"""The recording buttons are on screen in a computer's browser too. Synthetic data.

26-Oct (Angel's QA of Connie's video app): "no recording buttons when using it on
the browser". Measured the same day at 1280x720: Record / Pause / Stop / Finish
had their top edge at 731 px in a 720 px window, and the studio is one screen
that never scrolls, so they could not be reached at all. The camera column kept
a full-window minimum height (since 20-Sep) and pushed the button row out.
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record

pytest.importorskip("playwright.sync_api")

BUTTONS = ["recordButton", "pauseButton", "finishClipButton", "finishSessionButton"]

# Each button: inside the window, and the thing a click at its middle lands on.
ON_SCREEN = """(ids) => ids.filter((id) => getComputedStyle(document.getElementById(id)).display !== 'none')
  .map((id) => {
    const el = document.getElementById(id);
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {id, top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height),
            reachable: r.height > 0 && r.top >= 0 && r.bottom <= innerHeight && !!hit && el.contains(hit)};
  })"""

SIZES = {
    "laptop-1280x720": {"width": 1280, "height": 720},
    "desktop-1440x900": {"width": 1440, "height": 900},
    "small-laptop-1024x640": {"width": 1024, "height": 640},
    "tablet-800x600": {"width": 800, "height": 600},
}


@pytest.mark.parametrize("size", SIZES.values(), ids=SIZES.keys())
def test_every_recording_button_is_on_screen_in_a_computer_browser(studio, size):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        context = browser.new_context(viewport=size, permissions=["camera", "microphone"])
        page = context.new_page()
        page.add_init_script(LANDSCAPE_CAMERA)
        page.goto(f"{studio['base']}/record")
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")
        page.locator("#hookView .hook-option").first.locator(".hook-use").click()
        page.wait_for_selector("#studioView:not([hidden])")
        page.wait_for_function(
            "() => document.getElementById('camera').srcObject && document.getElementById('cameraEmpty').hidden",
            timeout=30000,
        )
        idle = page.evaluate(ON_SCREEN, BUTTONS)
        assert len(idle) == 4 and all(b["reachable"] for b in idle), f"buttons off screen before Record: {idle}"
        reader = page.evaluate("() => document.getElementById('reader').getBoundingClientRect().height")
        assert reader >= 120, f"the words have no room left: reader is {reader}px tall"
        # While recording: Pause, Stop and Finish on the foot of the camera.
        _record(page, 2)
        live = page.evaluate(ON_SCREEN, BUTTONS)
        assert {b["id"] for b in live} >= {"pauseButton", "finishSessionButton"}, live
        assert all(b["reachable"] for b in live), f"buttons off screen while recording: {live}"
        page.click("#pauseButton")
        page.wait_for_function("() => document.getElementById('pauseButton').textContent.trim() === 'Resume'")
        context.close()
        browser.close()
