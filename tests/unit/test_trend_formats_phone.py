"""Phone and desktop proof of trend formats (T-25834): the hook studio's format card
(pick, the script being written, the draft to read and accept, the steps with their
drawings) and the recording screen's step cards, one per step with its drawing.
Real pages and routers on a throwaway SQLite file, headless Chromium, the writer
stubbed. Synthetic data. Screenshots land in the test's tmp folder, or in
TCE_PROOF_DIR when it is set."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tce.api.routers import hooks as hooks_router
from tce.hooks import format_library, formats, library
from tests.unit.test_recording_studio_mobile import PHONE, WS
from tests.unit.test_visual_hook_recording_phone import _open, studio  # noqa: F401 - the shared fixture

pytest.importorskip("playwright.sync_api")

GBB = formats.GOOD_BETTER_BEST
DESKTOP = {"width": 1280, "height": 900}
LINES = {
    "open": "Three ways to plan a course.",
    "good": "Good: a list of topics.",
    "better": "Better: one lesson a week, each with a task.",
    "best": "Best: a plan built from what your students ask.",
    "close": "I use the last one for every course.",
}

PAGE_MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const card = document.querySelector('[data-format-card]');
  const texty = [...card.querySelectorAll('h3, p, label, textarea, button, summary, li span, li strong')].filter((e) => r(e).width);
  const imgs = [...card.querySelectorAll('img')].filter((e) => r(e).width);
  const buttons = [...card.querySelectorAll('button, summary, select')].filter((e) => r(e).width);
  const overlaps = [];
  for (let i = 0; i < buttons.length; i++) for (let j = i + 1; j < buttons.length; j++) {
    const a = r(buttons[i]), b = r(buttons[j]);
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push(i + '/' + j);
  }
  return {
    smallest: Math.min(...texty.map((e) => parseFloat(getComputedStyle(e).fontSize))),
    imgsLoaded: imgs.every((i) => i.complete && i.naturalWidth > 0), imgs: imgs.length,
    lowestButton: Math.min(...buttons.map((b) => r(b).height)),
    overlaps,
    overflowX: document.documentElement.scrollWidth > innerWidth + 1,
    cardInside: r(card).right <= innerWidth + 1 && r(card).left >= -1,
    script: card.querySelector('[data-format-script]') && card.querySelector('[data-format-script]').dataset.formatScript,
    lines: card.querySelectorAll('[data-format-line]').length,
    said: (card.querySelector('.format-script-said') || {}).textContent || '',
    exampleWords: [...card.querySelectorAll('.format-example-word')].map((e) => e.textContent),
  };
}
"""

SHEET_MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const sheet = document.getElementById('formatSheet');
  const kids = [...sheet.querySelectorAll('img, h2, p, li, button, .visual-hook-label')].filter((e) => r(e).width);
  const overlaps = [];
  for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) {
    const a = r(kids[i]), b = r(kids[j]);
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push(kids[i].tagName + '/' + kids[j].tagName);
  }
  const img = document.getElementById('formatStepDrawing');
  return {
    open: !sheet.hidden,
    kicker: document.getElementById('formatSheetKicker').textContent,
    title: document.getElementById('formatSheetTitle').textContent,
    say: document.getElementById('formatStepSay').textContent,
    screen: document.getElementById('formatStepScreen').textContent,
    coach: [...document.querySelectorAll('#formatStepCoach li')].map((li) => li.textContent),
    next: document.getElementById('formatStepNext').textContent,
    backDisabled: document.getElementById('formatStepBack').disabled,
    drawn: img.complete && img.naturalWidth > 0, src: img.getAttribute('src'),
    smallest: Math.min(...kids.filter((e) => e.tagName !== 'IMG').map((e) => parseFloat(getComputedStyle(e).fontSize))),
    overlaps,
    covers: !sheet.hidden && r(sheet).top <= 0 && r(sheet).height >= innerHeight - 1,
    overflowX: document.documentElement.scrollWidth > innerWidth + 1,
    line: document.getElementById('trendFormat').hidden ? null : document.querySelector('#trendFormat .visual-hook-line').textContent,
  };
}
"""


def _shots(tmp_path) -> Path:
    out = Path(os.environ.get("TCE_PROOF_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _browser(pw):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return pw.chromium.launch(headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    except PlaywrightError as exc:  # pragma: no cover
        pytest.skip(f"Chromium is not installed for Playwright: {exc}")


def test_recording_screen_walks_the_format_step_by_step(studio, tmp_path):  # noqa: F811
    from playwright.sync_api import sync_playwright

    out = _shots(tmp_path)
    cid = studio["candidate_id"]
    week = hooks_router._week_key()
    lineup = {"primary": [{"candidate_id": cid, "title": "Plan the course", "filmed": False}], "reserve": []}
    asyncio.run(format_library.pick(WS, week, GBB.id, lineup, cid))
    asyncio.run(format_library.set_script(WS, week, GBB.id, cid, {"state": "approved", "lines": LINES, "detail": "x"}))
    with sync_playwright() as pw:
        browser = _browser(pw)
        context = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
                                      permissions=["camera", "microphone"])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _open(page, studio["base"], cid)
        page.wait_for_selector("#formatSheet:not([hidden])")
        for index, step in enumerate(GBB.steps):
            page.wait_for_function("(() => { const i = document.getElementById('formatStepDrawing');"
                                   " return i.complete && i.naturalWidth > 0; })()", timeout=10000)
            page.wait_for_timeout(400)  # past the tap highlight, so the picture shows the page itself
            m = page.evaluate(SHEET_MEASURE)
            page.screenshot(path=str(out / f"format-step-{index + 1}-{step.id}-390.png"))
            assert m["open"] and m["covers"] and m["drawn"], m
            assert m["kicker"] == f"Good, better, best, step {index + 1} of 5" and m["title"] == step.label, m
            assert m["say"] == f"Say: {LINES[step.id]}" and m["coach"] == list(step.coach), m
            assert m["src"] == f"/api/v1/hooks/formats/good-better-best/drawing/{step.id}.svg", m
            assert m["backDisabled"] == (index == 0) and m["smallest"] >= 15, m
            assert not m["overlaps"] and not m["overflowX"], m
            assert m["next"] == ("Ready to record" if index == 4 else "Next step"), m
            if step.word:
                assert m["screen"] == f"On screen: {step.screen}", m
            page.tap("#formatStepNext")
        page.wait_for_selector("#formatSheet", state="hidden")
        m = page.evaluate(SHEET_MEASURE)
        page.screenshot(path=str(out / "format-studio-line-390.png"))
        assert m["line"] == "Format: Good, better, best", m
        page.tap("#trendFormatHow")
        page.wait_for_selector("#formatSheet:not([hidden])")
        page.tap("#formatStepNext")
        page.tap("#formatStepBack")
        assert page.evaluate(SHEET_MEASURE)["title"] == "The topic"
        assert not errors, errors
        browser.close()


def test_hook_studio_format_card_from_pick_to_accepted_script(studio, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    out = _shots(tmp_path)
    cid = studio["candidate_id"]
    week = hooks_router._week_key()
    lineup = {"primary": [{"candidate_id": cid, "title": "Plan the course", "big_idea": "", "reason": "", "filmed": False}],
              "reserve": []}

    async def fake_lineup(_sm, _ws):
        return lineup

    async def fake_fill(_sm, ws, wk, format_id, candidate_id, topic):
        await asyncio.sleep(1.5)  # the writer takes a moment; the card says it is writing meanwhile
        await format_library.set_script(ws, wk, format_id, candidate_id, {
            "state": "ready", "lines": LINES, "names": {"good": "Topics", "better": "Weekly", "best": "Asked"},
            "detail": "Written from its script. Read it, change any line, then accept it.",
        })

    async def enabled():
        return True

    from tce.api import dashboard

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)  # the flag lives in the real database
    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    monkeypatch.setattr(hooks_router.format_script, "fill", fake_fill)
    with sync_playwright() as pw:
        browser = _browser(pw)
        for name, viewport, mobile in (("390", PHONE, True), ("1280", DESKTOP, False)):
            library.write_store(WS, {"favorites": [], "weeks": {}})
            context = browser.new_context(viewport=viewport, device_scale_factor=2, is_mobile=mobile, has_touch=mobile)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{studio['base']}/hooks")
            page.wait_for_selector("[data-format-card]")
            page.wait_for_function("[...document.querySelectorAll('[data-format-card] img')]"
                                   ".every((i) => i.complete && i.naturalWidth > 0)", timeout=10000)
            m = page.evaluate(PAGE_MEASURE)
            page.screenshot(path=str(out / f"format-card-new-{name}.png"))
            assert m["exampleWords"] == ["GOOD", "BETTER", "BEST"] and m["imgsLoaded"], m
            assert not m["overflowX"] and m["cardInside"] and m["smallest"] >= 15 and m["lowestButton"] >= 44, m
            page.click("[data-format-pick]")
            page.wait_for_selector("[data-format-script='writing']")
            page.screenshot(path=str(out / f"format-card-writing-{name}.png"))
            said = page.evaluate(PAGE_MEASURE)["said"]
            assert "Writing the Good, better, best script" in said and "Started less than a minute ago." in said, said
            page.wait_for_selector("[data-format-script='ready']", timeout=15000)
            page.click(".format-steps-box summary")
            page.wait_for_timeout(300)
            m = page.evaluate(PAGE_MEASURE)
            page.screenshot(path=str(out / f"format-card-ready-{name}.png"), full_page=True)
            assert m["lines"] == 5 and m["imgs"] == 6 and m["imgsLoaded"], m
            assert not m["overflowX"] and not m["overlaps"] and m["smallest"] >= 15, m
            page.fill("#fmt-good-better-best-close", "I use the last one, every course.")
            page.click("[data-format-accept]")
            page.wait_for_selector("[data-format-script='approved']")
            entry = format_library.current(WS, week, GBB.id)
            assert entry["script"]["state"] == "approved" and entry["script"]["lines"]["close"] == "I use the last one, every course."
            assert "with your changes" in page.evaluate(PAGE_MEASURE)["said"]
            page.screenshot(path=str(out / f"format-card-accepted-{name}.png"))
            assert not errors, errors
            context.close()
        browser.close()
    # the hook library beside it is untouched by the format's writes
    assert library.read_store(WS)["favorites"] == []
