"""The Hooks page fits a phone screen when cards carry a long video title (T-26008).

Ziv's phone (about 412 px wide) showed the good, better, best card running past its
border and the whole page wider than the screen, once the format sat on a video and
"Put it on another video" listed this week's titles. A select sizes to its longest
option, and the card let that width push every column out. This rig puts the format
AND a hook on a video, with a week of long titles, and measures the page at 360, 412
and desktop width: nothing may be wider than the screen, and no card may spill past
its own border. Real pages and routers on a throwaway SQLite file, headless Chromium,
synthetic data. Screenshots land in the test's tmp folder, or in TCE_PROOF_DIR."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tce.api.routers import hooks as hooks_router
from tce.hooks import format_library, formats, library
from tce.hooks.catalog import HOOKS
from tests.unit.test_recording_studio_mobile import WS
from tests.unit.test_visual_hook_recording_phone import studio  # noqa: F401 - the shared fixture

pytest.importorskip("playwright.sync_api")

GBB = formats.GOOD_BETTER_BEST
LONG = "An AI that drafts your proposals works because of the setup, not the AI"
SIZES = (
    ("360", {"width": 360, "height": 780}, True),
    ("412", {"width": 412, "height": 892}, True),
    ("1280", {"width": 1280, "height": 900}, False),
)

MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const spills = [];
  for (const card of document.querySelectorAll('[data-format-card], [data-hook-card]')) {
    const box = r(card);
    if (box.right > innerWidth + 1 || box.left < -1) spills.push('card past screen: ' + (card.dataset.formatCard || card.dataset.hookCard));
    for (const el of card.querySelectorAll('*')) {
      const b = r(el);
      if (!b.width || el.closest('.format-example-word')) continue;
      if (b.right > box.right + 1 || b.left < box.left - 1) {
        spills.push((card.dataset.formatCard || card.dataset.hookCard) + ' ' + el.tagName.toLowerCase()
          + '.' + String(el.className || '').split(' ')[0] + ' ' + Math.round(b.left) + '-' + Math.round(b.right)
          + ' vs card ' + Math.round(box.left) + '-' + Math.round(box.right));
        if (spills.length > 12) break;
      }
    }
  }
  return {
    scrollWidth: document.documentElement.scrollWidth, innerWidth, clientWidth: document.documentElement.clientWidth,
    spills,
    hookSelects: document.querySelectorAll('[data-hook-move]').length,
    formatCards: document.querySelectorAll('[data-format-card], [data-trend-card]').length,
    pointer: !!document.querySelector('.trends-pointer a[data-go="/trends"]'),
    hookPicked: !!document.querySelector('[data-hook-card].is-picked'),
    smallest: Math.min(...[...document.querySelectorAll('[data-hook-card] p, [data-hook-card] label span, [data-hook-card] select, .trends-pointer')]
      .filter((e) => r(e).width).map((e) => parseFloat(getComputedStyle(e).fontSize))),
  };
}
"""


def _shots(tmp_path) -> Path:
    out = Path(os.environ.get("TCE_PROOF_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def test_hooks_page_fits_the_phone_with_long_video_titles(studio, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard

    out = _shots(tmp_path)
    cid = studio["candidate_id"]
    week = hooks_router._week_key()
    lineup = {"primary": [
        {"candidate_id": cid, "title": LONG, "big_idea": "", "reason": "", "filmed": False},
        {"candidate_id": "b2b2b2b2-0000-4000-8000-000000000002",
         "title": "Why most course launches stall in the second week and what to do about it",
         "big_idea": "", "reason": "", "filmed": False},
        {"candidate_id": "c3c3c3c3-0000-4000-8000-000000000003", "title": "Plan the course",
         "big_idea": "", "reason": "", "filmed": False},
    ], "reserve": []}

    async def fake_lineup(_sm, _ws):
        return lineup

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)  # the flag lives in the real database
    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    library.write_store(WS, {"favorites": [], "weeks": {}})
    asyncio.run(format_library.pick(WS, week, GBB.id, lineup, cid))
    asyncio.run(format_library.set_script(WS, week, GBB.id, cid, {
        "state": "ready", "lines": {"open": "Three ways to plan a course."}, "detail": "Written from its script."}))
    asyncio.run(library.pick(WS, week, HOOKS[0].id, lineup, cid))

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
            page.wait_for_selector("[data-hook-card].is-picked")
            page.wait_for_timeout(300)
            m = page.evaluate(MEASURE)
            page.evaluate("document.querySelector('[data-hook-move]').scrollIntoView({block: 'center'})")
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / f"hooks-page-{name}.png"))
            page.screenshot(path=str(out / f"hooks-page-full-{name}.png"), full_page=True)
            m["asked"] = viewport["width"]
            results[name] = m
            assert not errors, errors
            context.close()
        browser.close()
    for name, m in results.items():
        # T-26074: the trend card left the hooks page for its own Trends page; one line points there
        assert m["formatCards"] == 0 and m["pointer"] and m["hookPicked"] and m["hookSelects"] >= 1, (name, m)
        # a phone widens its layout to fit wide content and zooms out, so compare with the screen asked for
        assert m["innerWidth"] == m["asked"] and m["scrollWidth"] <= m["asked"], (name, m)
        assert not m["spills"], (name, m)
        assert m["smallest"] >= 15, (name, m)
