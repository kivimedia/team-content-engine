"""The moving example on the left of every hook, on a phone (27-Nov-2026, T-25911).

Ziv asked for a short looping example beside each hook that plays on his phone, so he
can tell the hooks apart at a glance. The clips were already there, carried only by the
autoplay attribute: in a real signed-in browser on 27 Nov all ten loaded and sat frozen
on a dark first frame. These tests model the two ways a phone stops a clip:

- the browser ignores the autoplay attribute (only a play() call starts a clip);
- the phone refuses play() too until a touch (battery saving).

Real hooks page and routers on a throwaway SQLite file, headless Chromium at 390 wide.
Screenshots land in the test's tmp folder, or in TCE_PROOF_DIR when it is set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tce.api.routers import hooks as hooks_router
from tce.hooks import library
from tests.unit.test_recording_studio_mobile import PHONE, WS
from tests.unit.test_visual_hook_recording_phone import studio  # noqa: F401 - the shared fixture

pytest.importorskip("playwright.sync_api")

# Every clip start is recorded; a start the page did not ask for (the autoplay attribute)
# is undone at once, as on a browser that ignores the attribute.
IGNORE_AUTOPLAY = """
(() => {
  const real = HTMLMediaElement.prototype.play;
  window.__asked = new WeakSet();
  HTMLMediaElement.prototype.play = function () { window.__asked.add(this); return real.call(this); };
  document.addEventListener('play', (e) => { if (!window.__asked.has(e.target)) e.target.pause(); }, true);
})();
"""

# On top of that, play() is refused until the person touches the page (battery saving).
REFUSE_UNTIL_TOUCH = """
(() => {
  const real = HTMLMediaElement.prototype.play;
  window.__touched = false;
  window.addEventListener('pointerdown', () => { window.__touched = true; }, true);
  HTMLMediaElement.prototype.play = function () {
    if (!window.__touched) {
      return Promise.reject(new DOMException('refused while saving battery', 'NotAllowedError'));
    }
    return real.call(this);
  };
})();
"""

MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const onScreen = (el) => { const b = r(el); return b.bottom > 0 && b.top < innerHeight; };
  const clips = [...document.querySelectorAll('[data-hook-card]')].map((card) => {
    const box = card.querySelector('.hook-clip') || card.querySelector('video.hook-preview');
    const v = card.querySelector('video.hook-preview');
    const body = card.querySelector('.hook-body');
    const badge = card.querySelector('.hook-clip-play');
    return {
      id: card.dataset.hookCard, onScreen: onScreen(v), paused: v.paused, t: v.currentTime,
      loop: v.loop, muted: v.muted, ready: v.readyState, width: v.videoWidth,
      left: r(box).right <= r(body).left + 1 && r(box).left <= r(body).left,
      badge: !!badge && getComputedStyle(badge).display !== 'none', badgeText: badge ? badge.textContent : null,
      badgeSize: badge ? parseFloat(getComputedStyle(badge).fontSize) : 0,
      badgeInside: !!badge && r(badge).left >= r(box).left - 1 && r(badge).right <= r(box).right + 1,
    };
  });
  return { clips, overflowX: document.documentElement.scrollWidth > innerWidth + 1 };
}
"""


def _shots(tmp_path) -> Path:
    out = Path(os.environ.get("TCE_PROOF_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _page(pw, scripts):
    from playwright.sync_api import Error as PlaywrightError

    try:
        browser = pw.chromium.launch(headless=True)
    except PlaywrightError as exc:  # pragma: no cover
        pytest.skip(f"Chromium is not installed for Playwright: {exc}")
    context = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
    for script in scripts:
        context.add_init_script(script)
    return browser, context.new_page()


def _serve_hooks(studio, monkeypatch):
    lineup = {"primary": [{"candidate_id": studio["candidate_id"], "title": "Plan the course", "big_idea": "",
                           "reason": "", "filmed": False}], "reserve": []}

    async def fake_lineup(_sm, _ws):
        return lineup

    async def enabled():
        return True

    from tce.api import dashboard

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)  # the flag lives in the real database
    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    library.write_store(WS, {"favorites": [], "weeks": {}})


def _open_hooks(page, base):
    page.goto(f"{base}/hooks")
    page.wait_for_selector("[data-hook-card] video.hook-preview")
    page.wait_for_function("[...document.querySelectorAll('video.hook-preview')].slice(0, 2)"
                           ".every((v) => v.readyState >= 2)", timeout=15000)
    # On a phone the trend format card comes first: scroll to where the openings start.
    page.evaluate("document.querySelector('.hook-grid-title').scrollIntoView({block: 'start'})")


def test_every_hook_has_its_example_on_the_left_and_it_moves_on_a_phone(studio, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    _serve_hooks(studio, monkeypatch)
    out = _shots(tmp_path)
    with sync_playwright() as pw:
        browser, page = _page(pw, [IGNORE_AUTOPLAY])
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _open_hooks(page, studio["base"])
        page.wait_for_timeout(1500)
        m = page.evaluate(MEASURE)
        page.screenshot(path=str(out / "hook-clips-moving-390.png"))
        assert len(m["clips"]) == 10, m
        assert all(c["left"] and c["loop"] and c["muted"] for c in m["clips"]), m
        shown = [c for c in m["clips"] if c["onScreen"]]
        assert shown, m
        for clip in shown:
            assert not clip["paused"] and clip["t"] > 0.6 and not clip["badge"], clip
        assert not m["overflowX"] and not errors, (m, errors)

        # Scrolled past, a clip stops; scrolled to, the next one starts.
        first, last = m["clips"][0]["id"], m["clips"][-1]["id"]
        page.locator(f'[data-hook-card="{last}"] video').scroll_into_view_if_needed()
        page.wait_for_timeout(1500)
        m = page.evaluate(MEASURE)
        by_id = {c["id"]: c for c in m["clips"]}
        assert by_id[first]["paused"] and not by_id[first]["onScreen"], by_id[first]
        assert not by_id[last]["paused"] and by_id[last]["t"] > 0, by_id[last]
        browser.close()


def test_a_phone_that_refuses_shows_play_and_one_touch_starts_the_clips(studio, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    _serve_hooks(studio, monkeypatch)
    out = _shots(tmp_path)
    with sync_playwright() as pw:
        browser, page = _page(pw, [IGNORE_AUTOPLAY, REFUSE_UNTIL_TOUCH])
        _open_hooks(page, studio["base"])
        page.wait_for_timeout(1000)
        m = page.evaluate(MEASURE)
        page.screenshot(path=str(out / "hook-clips-refused-390.png"))
        shown = [c for c in m["clips"] if c["onScreen"]]
        assert shown, m
        for clip in shown:
            assert clip["paused"] and clip["badge"] and clip["badgeText"] == "▶ Play", clip
            assert clip["badgeSize"] >= 15 and clip["badgeInside"], clip

        page.tap(f'[data-hook-card="{shown[0]["id"]}"] .hook-clip')
        page.wait_for_timeout(1200)
        m = page.evaluate(MEASURE)
        page.screenshot(path=str(out / "hook-clips-after-touch-390.png"))
        for clip in [c for c in m["clips"] if c["onScreen"]]:
            assert not clip["paused"] and clip["t"] > 0 and not clip["badge"], clip
        browser.close()
