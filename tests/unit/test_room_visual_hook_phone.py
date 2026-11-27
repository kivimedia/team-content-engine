"""A video's own visual hook, from its topic page (T-26074).

Ziv, 27-Nov-2026: "when I actually go into a specific video then I should have an option
add a visual hook if it doesn't have an assigned hook and then I can choose for that
specific video." Real pages and routers on a throwaway SQLite file, headless Chromium,
the opening writer stubbed. Synthetic data. Screenshots land in the test's tmp folder,
or in TCE_PROOF_DIR when it is set."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tce.api.routers import hooks as hooks_router
from tce.hooks import library
from tests.unit.test_recording_studio_mobile import PHONE, WS
from tests.unit.test_visual_hook_recording_phone import studio  # noqa: F401 - the shared fixture

pytest.importorskip("playwright.sync_api")

DESKTOP = {"width": 1280, "height": 900}

MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const box = document.getElementById('roomHook');
  const kids = [...box.querySelectorAll('h2, p, strong, span, button, a, .tag')].filter((e) => r(e).width);
  const buttons = [...box.querySelectorAll('button')].filter((e) => r(e).width);
  return {
    shown: !box.hidden,
    text: box.textContent,
    open: (box.querySelector('[data-room-hook-open]') || {}).textContent || null,
    choices: box.querySelectorAll('[data-room-hook-pick]').length,
    smallest: Math.min(...kids.map((e) => parseFloat(getComputedStyle(e).fontSize))),
    lowestButton: buttons.length ? Math.min(...buttons.map((b) => r(b).height)) : 99,
    overflowX: document.documentElement.scrollWidth > innerWidth + 1,
    inside: [...box.querySelectorAll('*')].every((e) => !r(e).width || (r(e).right <= innerWidth + 1 && r(e).left >= -1)),
  };
}
"""


def _shots(tmp_path) -> Path:
    out = Path(os.environ.get("TCE_PROOF_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _room(cid):
    """The topic page's own read, answered in the browser: this rig serves the hook routes,
    not the editorial workspace's, and the section under test only needs a topic to sit in."""
    import json

    body = json.dumps({"candidate_id": cid, "title": "Plan the course", "brief": {"version": 1, "blocks": []},
                       "decision": None, "script": None, "history": []})

    def answer(route):
        route.fulfill(status=200, content_type="application/json", body=body)

    return answer


def _browser(pw):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return pw.chromium.launch(headless=True)
    except PlaywrightError as exc:  # pragma: no cover
        pytest.skip(f"Chromium is not installed for Playwright: {exc}")


def test_a_video_with_no_hook_gets_one_from_its_own_page(studio, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard

    out = _shots(tmp_path)
    cid = studio["candidate_id"]
    week = hooks_router._week_key()
    lineup = {"primary": [{"candidate_id": cid, "title": "Plan the course", "big_idea": "", "reason": "", "filmed": False}],
              "reserve": []}
    fitted: list[tuple[str, str]] = []

    async def fake_lineup(_sm, _ws):
        return lineup

    async def fake_fit(_sm, _ws, _week, candidate_id, hook_id):
        fitted.append((candidate_id, hook_id))

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)  # the flag lives in the real database
    monkeypatch.setattr(hooks_router, "_lineup", fake_lineup)
    monkeypatch.setattr(hooks_router.script_fit, "fit_script", fake_fit)
    with sync_playwright() as pw:
        browser = _browser(pw)
        for name, viewport, mobile in (("390", PHONE, True), ("1280", DESKTOP, False)):
            library.write_store(WS, {"favorites": [], "weeks": {}})
            fitted.clear()
            context = browser.new_context(viewport=viewport, device_scale_factor=2, is_mobile=mobile, has_touch=mobile)
            context.route(f"**/api/v1/editorial/topics/{cid}/room", _room(cid))
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{studio['base']}/topics/{cid}")
            page.wait_for_selector("#roomHook:not([hidden])")
            m = page.evaluate(MEASURE)
            assert m["open"] == "Add a visual hook" and "No visual hook on this video yet" in m["text"], m
            page.click("[data-room-hook-open]")
            page.wait_for_selector("[data-room-hook-pick]")
            page.evaluate("document.getElementById('roomHook').scrollIntoView({block: 'start'})")
            page.wait_for_timeout(300)
            m = page.evaluate(MEASURE)
            page.screenshot(path=str(out / f"room-hook-choose-{name}.png"))
            assert m["choices"] >= 3 and not m["overflowX"] and m["inside"], m
            assert m["smallest"] >= 15 and m["lowestButton"] >= 44, m
            first = page.get_attribute("[data-room-hook-pick]", "data-room-hook-pick")
            page.click(f"[data-room-hook-pick='{first}']")
            page.wait_for_selector("#roomHook .room-hook-on")
            m = page.evaluate(MEASURE)
            page.screenshot(path=str(out / f"room-hook-on-{name}.png"))
            assert m["open"] == "Change the visual hook" and m["choices"] == 0, m
            assert [(e["hook_id"], e["candidate_id"]) for e in library.read_store(WS)["weeks"][week]] == [(first, cid)]
            assert fitted == [(cid, first)]  # the opening is written for this video's own script
            assert not errors, errors
            context.close()
        # a topic that is not in this week says how to get a hook, with no button that would fail
        lineup["primary"] = []
        library.write_store(WS, {"favorites": [], "weeks": {}})
        context = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
        context.route(f"**/api/v1/editorial/topics/{cid}/room", _room(cid))
        page = context.new_page()
        page.goto(f"{studio['base']}/topics/{cid}")
        page.wait_for_selector("#roomHook:not([hidden])")
        m = page.evaluate(MEASURE)
        assert m["open"] is None and "Put this topic in this week first" in m["text"], m
        context.close()
        browser.close()
