"""One Record button at the bottom right that opens into the take buttons. Synthetic data.

22-Nov (T-24294), Ziv in the app: "the record button is on the left side. There's two
buttons in the middle that are useless, and then there's this finish button on the
right side ... I'm right handed, and I walk with a dog on a leash, and then it's hard
for me to click that record button. Also, I think we only need, like, one button on
the bottom right, and it's a record button. If I click on it, it changes to ... one for
pause ... one for finish ... And both of them are on the right side."

Measured at 390x844 on a phone, pressed for real, in each reader layout (words on top,
swapped, words over the video) and with the page right to left:
- before a take only Record shows, at the bottom right, nothing dead on screen;
- while a take runs Pause, Stop and Finish show, all on the right half, Stop lowest;
- between takes Record and Finish show, Record in the corner and Finish beside it.
Screenshots go to TCE_SHOT_DIR when set (else the test's tmp dir).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record, _studio_page

pytest.importorskip("playwright.sync_api")

IDS = ["recordButton", "pauseButton", "finishClipButton", "finishSessionButton"]

# Every recording button that is drawn: its box, and whether a tap at its middle lands on it.
SHOWN_JS = """(ids) => ids.map((id) => {
  const el = document.getElementById(id);
  const r = el.getBoundingClientRect();
  const shown = getComputedStyle(el).display !== 'none' && r.height > 0 && r.width > 0;
  const hit = shown && document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {id, shown, left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top),
          bottom: Math.round(r.bottom), height: Math.round(r.height), vw: innerWidth, vh: innerHeight,
          tappable: !!hit && el.contains(hit), disabled: el.disabled};
}).filter((b) => b.shown)"""

PHASE_JS = "() => document.querySelector('#studioView .controls').dataset.phase"


def _shots(tmp_path: Path) -> Path:
    out = Path(os.environ.get("TCE_SHOT_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _on_right(buttons, label):
    for b in buttons:
        assert b["left"] >= b["vw"] / 2 - 1, f"{label}: {b['id']} is not on the right half: {b}"
        assert b["right"] <= b["vw"] and b["top"] >= 0 and b["bottom"] <= b["vh"], f"{label}: off screen {b}"
        assert b["tappable"] and not b["disabled"], f"{label}: {b['id']} cannot be pressed: {b}"


def _check_idle(page, label):
    idle = page.evaluate(SHOWN_JS, IDS)
    assert [b["id"] for b in idle] == ["recordButton"], f"{label}: before a take only Record shows: {idle}"
    rec = idle[0]
    _on_right(idle, label)
    assert rec["vw"] - rec["right"] <= 24, f"{label}: Record is not at the right edge: {rec}"
    assert rec["height"] >= 56, f"{label}: Record is too small for a thumb: {rec}"


def _check_live(page, label):
    live = page.evaluate(SHOWN_JS, IDS)
    by = {b["id"]: b for b in live}
    assert set(by) == {"pauseButton", "finishClipButton", "finishSessionButton"}, f"{label}: {live}"
    _on_right(live, label)
    assert by["finishClipButton"]["bottom"] >= max(b["bottom"] for b in live), (
        f"{label}: Stop is not in the corner Record was in: {live}"
    )
    # The timer and the red flag never sit under a button.
    for flag in ("timer", "recordingFlag"):
        box = page.evaluate(
            "(id) => { const r = document.getElementById(id).getBoundingClientRect();"
            " return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; }", flag
        )
        for b in live:
            apart = box["right"] <= b["left"] or box["left"] >= b["right"] or box["bottom"] <= b["top"] or box["top"] >= b["bottom"]
            assert apart, f"{label}: {flag} sits under {b['id']}: {box} {b}"
    return by


def _check_between(page, label):
    page.wait_for_function(f"() => ({PHASE_JS})() === 'between'", timeout=30000)
    # Record is greyed for the moment the take is being saved, as it always was.
    page.wait_for_function("() => !document.getElementById('recordButton').disabled", timeout=30000)
    between = page.evaluate(SHOWN_JS, IDS)
    by = {b["id"]: b for b in between}
    assert set(by) == {"recordButton", "finishSessionButton"}, f"{label}: between takes {between}"
    rec, fin = by["recordButton"], by["finishSessionButton"]
    # Record keeps the corner; Finish sits right beside it. Two thumb-sized buttons do
    # not both fit in half of a 390 px phone, so Finish is held to the right two thirds.
    _on_right([rec], label)
    assert rec["vw"] - rec["right"] <= 24, f"{label}: Record left the corner: {rec}"
    assert rec["left"] - fin["right"] <= 12, f"{label}: Finish is not beside Record: {between}"
    assert (fin["left"] + fin["right"]) / 2 >= fin["vw"] / 3, f"{label}: Finish is too far left: {fin}"
    assert fin["tappable"] and not fin["disabled"], f"{label}: Finish cannot be pressed: {fin}"


def _stop(page):
    page.click("#finishClipButton")
    page.wait_for_function(
        "() => !document.getElementById('studioView').classList.contains('is-recording')", timeout=30000
    )


@pytest.mark.parametrize("direction", ["ltr", "rtl"])
def test_one_record_button_bottom_right_in_every_layout(studio, tmp_path, direction):  # noqa: F811
    from playwright.sync_api import sync_playwright

    shots = _shots(tmp_path)
    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA)
        assert page.viewport_size == {"width": 390, "height": 844}
        if direction == "rtl":
            # A Hebrew page: the page turns right to left with the Hebrew sheet on top.
            page.evaluate(
                "() => new Promise((done) => { document.documentElement.dir = 'rtl';"
                " const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = 'i18n-he.css';"
                " l.onload = done; l.onerror = done; document.head.append(l); })"
            )
            assert page.evaluate("() => getComputedStyle(document.body).direction") == "rtl"

        layouts = [("words-top", None), ("swapped", "#flipLayoutButton"), ("over-video", "#overlayButton")]
        first = True
        for name, toggle in layouts:
            if toggle:
                page.click(toggle)
            label = f"{direction} {name}"
            if first:
                _check_idle(page, label)
                page.screenshot(path=str(shots / f"t24294-{direction}-{name}-1-before.png"))
            _record(page, 2)
            _check_live(page, label)
            page.screenshot(path=str(shots / f"t24294-{direction}-{name}-2-during.png"))
            # Pause and Resume still work from the stack.
            page.click("#pauseButton")
            page.wait_for_function("() => document.getElementById('pauseButton').textContent.trim() === 'Resume'")
            _check_live(page, label + " paused")
            page.click("#pauseButton")
            _stop(page)
            _check_between(page, label)
            page.screenshot(path=str(shots / f"t24294-{direction}-{name}-3-between.png"))
            if toggle:
                page.click(toggle)
            first = False
        context.close()
        browser.close()
