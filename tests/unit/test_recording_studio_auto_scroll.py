"""The reader scrolls by itself while recording, like a teleprompter. Synthetic data.

26-Oct, Angel's QA of Connie's app: "Something that confused me: I thought the
script would automatically scroll if I continued reading it." The words now move
at a speed in words per minute (130 to start, steps of 10) from the moment Record
starts: Pause holds them, Resume carries on, Stop ends it, a finger on the words
holds them until three seconds after it lifts, and the end of the text is the end.

Drives headless Chromium at phone width with a fake camera, on a script long
enough to scroll for minutes. Nothing here calls a paid service or a real database.
"""

from __future__ import annotations

import re

import pytest

from tests.unit import test_recording_studio_mobile as mobile
from tests.unit.test_editorial_packets import good_output
from tests.unit.test_hebrew_studio_screens import server  # noqa: F401 - fixture
from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record, _studio_page

pytest.importorskip("playwright.sync_api")

# A real take is minutes long; eight short phrases fit on one screen and never scroll.
LONG_SCRIPT = [
    f"Phrase {n}: the coach keeps talking about the call, the pause and the question that follows it."
    for n in range(1, 61)
]
# Record gives a breath and the first line before the words move, so the line being
# read sits below the top edge, not under it.
LEAD_S = 3.0

# Where the words are, with the page's own clock so a slow test runner does not skew the rate.
AT_JS = "() => ({ top: document.getElementById('reader').scrollTop, at: performance.now() })"
# The rate 130 words a minute means for THIS text at THIS size: text height over word count.
EXPECTED_JS = """
(wpm) => {
  const lines = [...document.querySelectorAll('#reader .reader-line')];
  let words = 0;
  lines.forEach((line) => line.childNodes.forEach((node) => {
    if (node.nodeType === 1 && (node.classList.contains('reader-index') || node.tagName === 'BUTTON')) return;
    words += (node.textContent.match(/\\S+/g) || []).length;
  }));
  const height = lines.at(-1).getBoundingClientRect().bottom - lines[0].getBoundingClientRect().top;
  return (wpm / 60) * (height / words);
}
"""
TOUCH_JS = """
(type) => {
  const reader = document.getElementById('reader');
  const touch = new Touch({ identifier: 1, target: reader, clientX: 120, clientY: 600 });
  const touches = type === 'touchend' ? [] : [touch];
  reader.dispatchEvent(new TouchEvent(type, { touches, changedTouches: [touch], bubbles: true, cancelable: true }));
}
"""


@pytest.fixture
def long_script(monkeypatch):
    """The studio fixture seeds good_output(); this one gives it a script of sixty phrases.

    Listed before `studio` in a test's arguments, so it is patched before the seed runs."""
    monkeypatch.setattr(mobile, "good_output", lambda **over: good_output(script_phrases=LONG_SCRIPT, **over))


def _rate(page, seconds):
    """Pixels per second the words moved over the next `seconds`."""
    first = page.evaluate(AT_JS)
    page.wait_for_timeout(int(seconds * 1000))
    last = page.evaluate(AT_JS)
    return (last["top"] - first["top"]) / ((last["at"] - first["at"]) / 1000)


def _full_script(page):
    page.click("#scriptTab")
    page.wait_for_function("() => document.getElementById('reader').classList.contains('script')")
    page.evaluate("() => { document.getElementById('reader').scrollTop = 0; }")


def test_full_script_scrolls_by_itself_at_the_speed_shown(long_script, studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _full_script(page)
        assert page.locator("#scrollSpeedValue").inner_text().strip() == "130"
        assert page.get_attribute("#scrollToggle", "aria-pressed") == "true", "Full script starts with auto-scroll on"
        # Nothing moves before Record: he reads the opening to himself first.
        assert _rate(page, 1.0) == 0
        _record(page, LEAD_S + 0.6)
        moved = _rate(page, 3.0)
        expected = page.evaluate(EXPECTED_JS, 130)
        assert 0.7 * expected <= moved <= 1.3 * expected, f"{moved:.1f} px/s against {expected:.1f} px/s for 130 wpm"
        context.close()
        browser.close()
    assert not errors, errors


def test_pause_holds_the_words_resume_moves_them_stop_ends_it(long_script, studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        _full_script(page)
        _record(page, LEAD_S + 0.6)
        assert _rate(page, 1.0) > 2, "the words did not move while recording"
        page.click("#pauseButton")
        page.wait_for_timeout(300)
        assert _rate(page, 1.5) == 0, "Pause did not hold the words"
        page.click("#pauseButton")  # Resume
        page.wait_for_timeout(int((LEAD_S + 0.6) * 1000))
        assert _rate(page, 1.0) > 2, "Resume did not move the words again"
        with page.expect_response(lambda r: "recording-clips" in r.url and r.url.endswith("/finish"), timeout=60000):
            page.click("#finishClipButton")
        page.wait_for_timeout(300)
        assert _rate(page, 1.5) == 0, "the words kept moving after Stop"
        context.close()
        browser.close()


def test_a_finger_on_the_words_holds_them_until_three_seconds_after_it_lifts(long_script, studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        _full_script(page)
        _record(page, LEAD_S + 0.6)
        assert _rate(page, 1.0) > 2
        page.evaluate(TOUCH_JS, "touchstart")
        page.wait_for_timeout(200)
        assert _rate(page, 1.5) == 0, "the words moved under his finger"
        page.evaluate(TOUCH_JS, "touchend")
        page.wait_for_timeout(1000)
        assert _rate(page, 1.0) == 0, "the words moved again before three seconds"
        page.wait_for_timeout(2000)
        assert _rate(page, 1.0) > 2, "the words never moved again after the finger lifted"
        # A mouse wheel (desktop) is a hand on the words too.
        page.evaluate(
            "() => document.getElementById('reader').dispatchEvent(new WheelEvent('wheel', { deltaY: 1, bubbles: true }))"
        )
        page.wait_for_timeout(200)
        assert _rate(page, 1.5) == 0, "a wheel turn did not hold the words"
        context.close()
        browser.close()


def test_speed_plus_is_faster_and_the_end_of_the_text_stops_it(long_script, studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _full_script(page)
        _record(page, LEAD_S + 0.6)
        slow = _rate(page, 2.0)
        for _ in range(5):
            page.click("#scrollFaster")
        assert page.locator("#scrollSpeedValue").inner_text().strip() == "180"
        fast = _rate(page, 2.0)
        assert fast > slow * 1.2, f"Speed + did not speed it up: {slow:.1f} then {fast:.1f} px/s"
        # Remembered on this phone, every read and write guarded for private tabs.
        assert page.evaluate("() => localStorage.getItem('tce-autoscroll-wpm')") == "180"
        # The end of the text: the words stop there, nothing breaks.
        page.evaluate("() => { const r = document.getElementById('reader'); r.scrollTop = r.scrollHeight; }")
        page.wait_for_timeout(4000)
        end = page.evaluate("() => { const r = document.getElementById('reader'); return r.scrollHeight - r.clientHeight - r.scrollTop; }")
        assert end <= 1, f"{end}px short of the end"
        assert _rate(page, 1.0) == 0
        context.close()
        browser.close()
    assert not errors, errors


def test_points_start_with_auto_scroll_off_and_each_tab_keeps_its_own_switch(long_script, studio):  # noqa: F811
    """Points are glanced at, and Ziv jumps by number there; Full script is read word for word."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        assert page.get_attribute("#scrollToggle", "aria-pressed") == "false", "Points start with auto-scroll off"
        assert page.locator("#scrollSpeed").is_hidden(), "the speed shows only while auto-scroll is on"
        _record(page, LEAD_S + 0.6)
        assert _rate(page, 1.0) == 0, "Points moved by themselves"
        # Switched on in Points: it moves, and Full script keeps its own (on) switch.
        page.click("#scrollToggle")
        page.wait_for_timeout(int((LEAD_S + 0.4) * 1000))
        assert _rate(page, 1.0) > 2, "switched on mid-take, the points did not move"
        page.click("#scriptTab")
        assert page.get_attribute("#scrollToggle", "aria-pressed") == "true"
        page.click("#scrollToggle")
        page.click("#pointsTab")
        assert page.get_attribute("#scrollToggle", "aria-pressed") == "true", "Points forgot its own switch"
        assert page.evaluate(
            "() => [localStorage.getItem('tce-autoscroll-points'), localStorage.getItem('tce-autoscroll-script')]"
        ) == ["1", "0"]
        context.close()
        browser.close()


# Where a line's top is inside the words, in the reader's own scroll pixels.
LINE_AT_JS = """
(id) => {
  const reader = document.getElementById('reader');
  return document.getElementById(id).getBoundingClientRect().top - reader.getBoundingClientRect().top + reader.scrollTop;
}
"""


def test_a_point_number_moves_the_words_and_the_lit_number_follows_them(long_script, studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        _full_script(page)
        _record(page, LEAD_S + 0.6)
        # Point 3 starts at phrase 21 (sixty phrases over six points): the words go there...
        page.evaluate("() => document.querySelector('#beatRail [data-beat=\"2\"]').click()")
        page.wait_for_timeout(1500)
        landed = page.evaluate(LINE_AT_JS, "script-20") - page.evaluate("() => document.getElementById('reader').scrollTop")
        assert 40 <= landed <= 120, f"point 3 landed {landed:.0f}px from the top of the words"
        # ...and carry on from there.
        page.wait_for_timeout(1000)
        assert _rate(page, 1.0) > 2, "the words stopped after a point number"
        # Just above where point 4 starts: the words reach it and its number lights up.
        page.evaluate(
            "(top) => { document.getElementById('reader').scrollTop = top - 100; }",
            page.evaluate(LINE_AT_JS, "script-30"),
        )
        page.wait_for_function(
            "() => document.querySelector('#beatRail .is-current')?.dataset.beat === '3'", timeout=8000
        )
        context.close()
        browser.close()


RAIL_JS = """
() => {
  const read = (id, name) => document.getElementById(id)?.getAttribute(name) || null;
  const rail = document.querySelector('.size-rail');
  const visible = [...rail.querySelectorAll('*')]
    .filter((el) => el.getBoundingClientRect().height && getComputedStyle(el).visibility !== 'hidden')
    .flatMap((el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.nodeValue.trim()))
    .filter(Boolean);
  return {
    toggle: read('scrollToggle', 'aria-label'), toggleTitle: read('scrollToggle', 'title'),
    faster: read('scrollFaster', 'aria-label'), slower: read('scrollSlower', 'aria-label'),
    visible,
  };
}
"""


def test_the_auto_scroll_controls_speak_hebrew_on_a_hebrew_page(server):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        context = browser.new_context(
            viewport=mobile.PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
            permissions=["camera", "microphone"], locale="he-IL",
        )
        page = context.new_page()
        page.goto(f"{server['base']}/record")
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")
        page.locator("#hookView .hook-option").first.locator(".hook-use").click()
        page.wait_for_selector("#studioView:not([hidden])")
        page.click("#scriptTab")
        page.wait_for_selector("#scrollToggle")
        rail = page.evaluate(RAIL_JS)
        latin = re.compile(r"[A-Za-z]{3,}")
        for name in ("toggle", "toggleTitle", "faster", "slower"):
            assert rail[name] and not latin.search(rail[name]), rail
        assert not [text for text in rail["visible"] if latin.search(text)], rail
        # Switching it says what it did, in Hebrew.
        page.click("#scrollToggle")
        page.wait_for_selector("#notice:not([hidden])")
        notice = page.locator("#notice").inner_text()
        assert notice and not latin.search(notice), notice
        context.close()
        browser.close()
