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


TREND_MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const card = document.querySelector('[data-trend-card]');
  const texty = [...card.querySelectorAll("h2, p, a, button, summary, figcaption span")].filter((e) => r(e).width);
  const buttons = [...card.querySelectorAll('button, summary')].filter((e) => r(e).width);
  const overlaps = [];
  for (let i = 0; i < buttons.length; i++) for (let j = i + 1; j < buttons.length; j++) {
    const a = r(buttons[i]), b = r(buttons[j]);
    if (buttons[i].contains(buttons[j]) || buttons[j].contains(buttons[i])) continue;
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push(i + '/' + j);
  }
  const frames = [...card.querySelectorAll('.trend-play img')];
  const nav = [...document.querySelectorAll('#bottomNav a')].filter((a) => r(a).width);
  const navClipped = nav.filter((a) => a.scrollWidth > a.clientWidth + 1).map((a) => a.textContent.trim());
  const original = card.querySelector('.trend-example figcaption a');
  return {
    frames: frames.length, framesLoaded: frames.every((i) => i.complete && i.naturalWidth > 0),
    original: original ? original.href : null, originalNewTab: original ? original.target : null,
    by: (card.querySelector('.trend-example-by') || {}).textContent || '',
    decideButtons: [...card.querySelectorAll('[data-trend-decide]')].map((b) => b.textContent),
    textareas: document.querySelectorAll('#view textarea, #view select').length,
    ideas: [...document.querySelectorAll('.big-ideas-list strong')].map((e) => e.textContent),
    wanted: card.classList.contains('is-wanted'),
    smallest: Math.min(...texty.map((e) => parseFloat(getComputedStyle(e).fontSize))),
    lowestButton: Math.min(...buttons.map((b) => r(b).height)),
    overlaps,
    overflowX: document.documentElement.scrollWidth > innerWidth + 1,
    cardInside: r(card).right <= innerWidth + 1 && r(card).left >= -1,
    nav: nav.map((a) => a.textContent.trim()), navClipped,
    navCurrent: (document.querySelector('#bottomNav a[aria-current="page"]') || {}).textContent || '',
    navInside: nav.every((a) => r(a).right <= innerWidth + 1),
    video: (card.querySelector('iframe.trend-video') || {}).src || null,
    // the yes sits on the first screen, above the bottom menu, with the clip beside it
    yesOnFirstScreen: (() => { const b = card.querySelector('[data-choice="want"]'); const nav = document.getElementById('bottomNav');
      return !!b && r(b).bottom <= r(nav).top && r(b).top >= 0; })(),
  };
}
"""

# A tiny picture and a stand-in player, so the test never reaches YouTube itself.
PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf000000040001f61738550000000049454e44ae426082"
)


def test_trends_page_real_example_then_a_yes_goes_on_big_ideas(studio, tmp_path, monkeypatch):  # noqa: F811
    """T-26074 (Ziv, 27-Nov): a trend is understood from a real creator doing it, decided with
    one tap, and the yes lands on his big ideas list. No edit boxes on the page."""
    from playwright.sync_api import sync_playwright

    out = _shots(tmp_path)
    cid = studio["candidate_id"]
    lineup = {"primary": [{"candidate_id": cid, "title": "Plan the course", "big_idea": "", "reason": "", "filmed": False}],
              "reserve": []}
    picked: list[str] = []

    async def fake_lineup(_sm, _ws):
        return lineup

    async def fake_fill(*args):
        picked.append("script")

    async def enabled():
        return True

    from tce.api import dashboard

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)  # the flag lives in the real database
    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    monkeypatch.setattr(hooks_router.format_script, "fill", fake_fill)
    real = GBB.real[0]
    with sync_playwright() as pw:
        browser = _browser(pw)
        for name, viewport, mobile in (("390", PHONE, True), ("1280", DESKTOP, False)):
            library.write_store(WS, {"favorites": [], "weeks": {}})
            context = browser.new_context(viewport=viewport, device_scale_factor=2, is_mobile=mobile, has_touch=mobile)
            context.route("https://i.ytimg.com/**", lambda route: route.fulfill(body=PIXEL, content_type="image/png"))
            context.route("https://www.youtube-nocookie.com/**",
                          lambda route: route.fulfill(body="<p>player</p>", content_type="text/html"))
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{studio['base']}/trends")
            page.wait_for_selector("[data-trend-card]")
            page.wait_for_function("[...document.querySelectorAll('.trend-play img')]"
                                   ".every((i) => i.complete && i.naturalWidth > 0)", timeout=10000)
            page.wait_for_timeout(400)
            m = page.evaluate(TREND_MEASURE)
            page.screenshot(path=str(out / f"trends-new-{name}.png"))
            assert m["frames"] == 3 and m["framesLoaded"], m
            assert m["original"] == real.url and m["originalNewTab"] == "_blank" and real.channel in m["by"], m
            assert m["decideButtons"] == ["I want this one", "Not for me"] and m["textareas"] == 0, m
            assert m["ideas"] == [] and not m["wanted"] and m["yesOnFirstScreen"], m
            assert not m["overflowX"] and m["cardInside"] and not m["overlaps"], m
            assert m["smallest"] >= 15 and m["lowestButton"] >= 44, m
            labels = [n[1:] for n in m["nav"]]  # each label starts with its one-character icon
            assert "Trends" in labels and "Hooks" in labels and m["navCurrent"].endswith("Trends"), m
            assert not m["navClipped"] and m["navInside"], m
            page.click("[data-trend-decide][data-choice='want']")
            page.wait_for_selector("[data-trend-card].is-wanted")
            m = page.evaluate(TREND_MEASURE)
            page.screenshot(path=str(out / f"trends-wanted-{name}.png"))
            assert m["ideas"] == [GBB.name] and m["decideButtons"] == ["Take it off the list"], m
            assert format_library.wanted(WS)[0]["id"] == GBB.id and picked == []
            assert format_library.current(WS, hooks_router._week_key(), GBB.id) is None  # no video, no script
            page.click("[data-trend-play]")
            page.wait_for_selector("iframe.trend-video")
            m = page.evaluate(TREND_MEASURE)
            assert m["video"].startswith("https://www.youtube-nocookie.com/embed/" + real.video_id), m
            assert not m["overflowX"] and m["cardInside"], m
            page.screenshot(path=str(out / f"trends-playing-{name}.png"))
            page.click("[data-trend-decide]")
            page.wait_for_selector("[data-trend-decide][data-choice='pass']")
            assert format_library.wanted(WS) == []
            assert not errors, errors
            context.close()
        browser.close()
    # the hook library beside it is untouched by the trend's writes
    assert library.read_store(WS)["favorites"] == []
