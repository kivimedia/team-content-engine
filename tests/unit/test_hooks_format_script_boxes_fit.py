"""The trend format's script boxes show every line of their text (T-26039).

On the live Hooks page at 412 px the Better and Best boxes of the good, better, best
script held three lines in a two-line box (scrollHeight 83 against clientHeight 62), so
the last line showed half cut until he scrolled inside the box. This rig writes a script
whose lines run long, opens the Hooks page at 360, 412 and desktop width, and asks every
script box to be tall enough for its own text; then it types more into one box and asks
it to grow with the words. Real pages and routers on a throwaway SQLite file, headless
Chromium, synthetic data. Screenshots land in the test's tmp folder, or in TCE_PROOF_DIR."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tce.api.routers import hooks as hooks_router
from tce.hooks import format_library, formats, library
from tests.unit.test_recording_studio_mobile import WS
from tests.unit.test_visual_hook_recording_phone import studio  # noqa: F401 - the shared fixture

pytest.importorskip("playwright.sync_api")

GBB = formats.GOOD_BETTER_BEST
LINES = {
    "open": "Three ways to plan a course, and only one of them gets it finished.",
    "good": "Good: you write the outline first, so you know what each lesson is for before you record a word of it.",
    "better": ("Better: you write the outline and test the first lesson with five real people, so you hear "
               "where they get lost before you build the rest of the course around it."),
    "best": ("Best: you sell the course before you build it, then you write each lesson the week before you "
             "teach it live, so the people who paid shape every part of what you make."),
    "close": "Pick the one you can start this week, and tell me which in the comments.",
}
SIZES = (
    ("360", {"width": 360, "height": 780}, True),
    ("412", {"width": 412, "height": 892}, True),
    ("1280", {"width": 1280, "height": 900}, False),
)

MEASURE = """
() => [...document.querySelectorAll('[data-format-line]')].map((t) => ({
  step: t.dataset.formatLine, scroll: t.scrollHeight, client: t.clientHeight,
  font: parseFloat(getComputedStyle(t).fontSize),
}))
"""


def _shots(tmp_path) -> Path:
    out = Path(os.environ.get("TCE_PROOF_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def test_format_script_boxes_show_all_their_text(studio, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard

    out = _shots(tmp_path)
    cid = studio["candidate_id"]
    week = hooks_router._week_key()
    lineup = {"primary": [
        {"candidate_id": cid, "title": "Plan the course", "big_idea": "", "reason": "", "filmed": False},
        {"candidate_id": "b2b2b2b2-0000-4000-8000-000000000002", "title": "Launch week",
         "big_idea": "", "reason": "", "filmed": False},
    ], "reserve": []}

    async def fake_lineup(_sm, _ws):
        return lineup

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    library.write_store(WS, {"favorites": [], "weeks": {}})
    asyncio.run(format_library.pick(WS, week, GBB.id, lineup, cid))
    asyncio.run(format_library.set_script(WS, week, GBB.id, cid, {
        "state": "ready", "lines": LINES, "detail": "Written from its script."}))

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as exc:  # pragma: no cover
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        results = {}
        for name, viewport, mobile in SIZES:
            context = browser.new_context(viewport=viewport, device_scale_factor=2, is_mobile=mobile, has_touch=mobile)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{studio['base']}/hooks")
            page.wait_for_selector("[data-format-line='best']")
            page.wait_for_timeout(300)
            boxes = page.evaluate(MEASURE)
            page.evaluate("document.querySelector('[data-format-line=\"better\"]').scrollIntoView({block: 'center'})")
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / f"script-boxes-{name}.png"))
            # he adds words to a box: it grows with them instead of hiding the new line
            best = page.locator("[data-format-line='best']")
            best.click()
            page.keyboard.press("End")
            page.keyboard.type(" And you keep a list of every question they ask, for the next round.")
            page.wait_for_timeout(100)
            typed = page.evaluate("(() => { const t = document.querySelector('[data-format-line=\"best\"]');"
                                  " return {scroll: t.scrollHeight, client: t.clientHeight}; })()")
            results[name] = {"boxes": boxes, "typed": typed}
            assert not errors, errors
            context.close()
        browser.close()
    for name, m in results.items():
        steps = {b["step"] for b in m["boxes"]}
        assert {"better", "best"} <= steps, (name, m)
        cut = [b for b in m["boxes"] if b["scroll"] > b["client"] + 1]
        assert not cut, (name, cut)
        assert all(b["font"] >= 15 for b in m["boxes"]), (name, m)
        assert m["typed"]["scroll"] <= m["typed"]["client"] + 1, (name, m["typed"])
