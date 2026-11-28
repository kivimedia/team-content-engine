"""Openings still waiting for a proof clip (T-26347, 28-Nov-2026).

Ziv sent a reel with four openings to add to the hook library: a hand pushed at the
lens with a title, a colored wipe between shots, talking into an object as a mic, and
a title that swipes down. A hook joins the library only after its proof clip passes
the frame check, so these wait, beside the six from the first round. The Hooks page
lists them with what take each needs; none can be picked, starred or put on a video.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tce.hooks import catalog, library
from tests.unit.test_hook_library import LINEUP, WEEK, WS, run, store  # noqa: F401 - the shared fixture

FROM_THE_REEL = ("hand-title", "color-wipe", "object-mic", "title-drop")
FIRST_ROUND = ("speed-ramp", "beside-yourself", "out-of-frame", "throw-catch", "hand-cover", "beat-high-five")


def test_the_four_from_the_reel_and_the_six_from_the_first_round_wait():
    ids = [h.id for h in catalog.WAITING]
    assert ids == list(FROM_THE_REEL + FIRST_ROUND)
    assert len(set(ids)) == len(ids)


def test_a_waiting_hook_cannot_be_picked_or_starred():
    for hook in catalog.WAITING:
        assert hook.id not in catalog.BY_ID, hook.id
        assert hook not in catalog.HOOKS, hook.id
    assert len(catalog.HOOKS) == 10


def test_each_waiting_hook_has_coach_lines_script_need_and_what_it_needs():
    for hook in catalog.WAITING:
        assert len(hook.coach) == 3, hook.id
        assert hook.script_need and hook.waiting_for and hook.record and hook.what, hook.id
        for text in (hook.name, hook.what, hook.record, hook.script_need, hook.waiting_for, *hook.coach):
            assert "\u2014" not in text and "\u2013" not in text and "--" not in text, hook.id
    # The two the reel's style allows from a take he already has say so; the other two ask for a fresh one.
    by_id = {h.id: h for h in catalog.WAITING}
    for hook_id in ("color-wipe", "title-drop"):
        assert "existing takes" in by_id[hook_id].waiting_for
    for hook_id in ("hand-title", "object-mic"):
        assert by_id[hook_id].waiting_for.startswith("A fresh take from you")
    assert "hand cover" in by_id["hand-title"].waiting_for


def test_picking_a_waiting_hook_is_refused(store):  # noqa: F811
    with pytest.raises(library.HookError) as refused:
        run(library.pick(WS, WEEK, "hand-title", LINEUP))
    assert refused.value.status == 404


def test_the_week_payload_lists_them_after_the_proved_ones(store):  # noqa: F811
    data = run(library.library(WS, WEEK, LINEUP, lambda i: f"hooks/{i}/preview"))
    assert [w["id"] for w in data["waiting"]] == list(FROM_THE_REEL + FIRST_ROUND)
    assert data["proved"] == 10 and len(data["hooks"]) == 10
    assert all(w["waiting_for"] and len(w["coach"]) == 3 for w in data["waiting"])


MEASURE = """
() => {
  const sec = document.querySelector('.hook-waiting');
  if (!sec) return {sec: false};
  const items = [...sec.querySelectorAll('[data-hook-waiting]')];
  const r = sec.getBoundingClientRect();
  const grid = document.querySelector('.hook-grid').getBoundingClientRect();
  const fs = (el) => parseFloat(getComputedStyle(el).fontSize);
  return {
    sec: true,
    title: sec.querySelector('h2').textContent,
    ids: items.map((li) => li.dataset.hookWaiting),
    needs: items.map((li) => li.querySelector('.hook-needs').textContent),
    buttons: sec.querySelectorAll('button, select, [data-hook-pick], [data-hook-fav]').length,
    videos: sec.querySelectorAll('video').length,
    belowGrid: r.top >= grid.bottom - 1,
    width: r.width,
    overflowX: document.documentElement.scrollWidth > window.innerWidth,
    smallest: Math.min(...[...sec.querySelectorAll('p, h3')].map(fs)),
  };
}
"""


def _in_process_page(pw, client):
    """A 390 wide phone whose every request is answered in this process: no port is
    opened, so it runs where loopback is closed as well as in CI."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        browser = pw.chromium.launch(headless=True)
    except PlaywrightError as exc:  # pragma: no cover
        pytest.skip(f"Chromium is not installed for Playwright: {exc}")
    context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                  is_mobile=True, has_touch=True)

    def answer(route):
        req = route.request
        path = req.url.split("://", 1)[1].split("/", 1)[1]
        got = client.request(req.method, "/" + path, content=req.post_data_buffer)
        headers = {k: v for k, v in got.headers.items() if k.lower() not in ("content-length", "content-encoding")}
        route.fulfill(status=got.status_code, headers=headers, body=got.content)

    context.route("http://tce.test/**", answer)
    return browser, context.new_page()


def test_the_hooks_page_shows_them_read_only_on_a_phone(store, tmp_path, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard
    from tests.unit.test_hook_library import _client

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)  # the flag lives in the real database
    client = _client(monkeypatch, store)
    client.app.include_router(dashboard.router)
    out = Path(os.environ.get("TCE_PROOF_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser, page = _in_process_page(pw, client)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://tce.test/hooks")
        page.wait_for_selector(".hook-waiting [data-hook-waiting]")
        page.evaluate("document.querySelector('.hook-waiting').scrollIntoView({block: 'start'})")
        page.wait_for_timeout(400)
        m = page.evaluate(MEASURE)
        page.screenshot(path=str(out / "hook-waiting-390.png"))
        browser.close()
    assert m["sec"], m
    assert m["title"] == "Coming next: 10 openings", m
    assert m["ids"] == list(FROM_THE_REEL + FIRST_ROUND), m
    assert m["needs"][0].startswith("Needs: A fresh take from you"), m
    assert m["buttons"] == 0 and m["videos"] == 0, m
    assert m["belowGrid"] and not m["overflowX"] and m["width"] <= 390, m
    assert m["smallest"] >= 15.5, m
    assert not errors, errors
