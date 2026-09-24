"""The reader's background darkness and the paging point numbers, on a phone. Synthetic data.

24-Sep: "under the A+ and A- buttons add buttons that allow me to change the
background darkness so that the letters pop more. also the left number icons -
if there are more than 5 the sixth one is an arrow for the next batch of points
and if I click it the top number changes to up button".
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import PHONE, studio  # noqa: F401 - fixture

pytest.importorskip("playwright.sync_api")

TAPPABLE = """(el) => { const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return !!hit && (hit === el || el.contains(hit)); }"""
WHAT_COVERS = """(el) => { const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  const rail = document.getElementById('beatRail').getBoundingClientRect();
  return {arrow: [r.top, r.bottom, el.textContent], rail: [rail.top, rail.bottom],
          hit: hit && (hit.id || hit.className), vh: innerHeight}; }"""


def _open_studio(pw, base, viewport):
    browser = pw.chromium.launch(
        headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
    )
    context = browser.new_context(
        viewport=viewport, device_scale_factor=2, is_mobile=True, has_touch=True,
        permissions=["camera", "microphone"],
    )
    page = context.new_page()
    page.goto(f"{base}/record")
    page.wait_for_selector(".idea-card")
    page.click(".idea-card")
    page.locator("#hookView .hook-option").first.locator(".hook-use").click()
    page.wait_for_selector("#studioView:not([hidden])")
    return browser, context, page


def test_darker_background_makes_the_words_white_and_is_remembered(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _open_studio(pw, studio["base"], PHONE)
        read = "() => { const r = getComputedStyle(document.getElementById('reader'));" \
               " return [r.backgroundColor, r.color]; }"
        assert page.locator("#shadeLighter").is_disabled(), "already at the lightest step"
        for _ in range(4):
            page.click("#shadeDarker")
        bg, fg = page.evaluate(read)
        assert bg == "rgb(0, 0, 0)" and fg == "rgb(255, 255, 255)", (bg, fg)
        assert page.locator("#shadeDarker").is_disabled(), "the darkest step is the last"
        # Both new buttons sit under A-, inside the rail, and can be tapped.
        order = page.evaluate(
            "() => ['textBigger','textSmaller','shadeDarker','shadeLighter']"
            ".map((id) => document.getElementById(id).getBoundingClientRect().top)"
        )
        assert order == sorted(order), f"not stacked under A+ and A-: {order}"
        for bid in ("#shadeDarker", "#shadeLighter"):
            assert page.eval_on_selector(bid, TAPPABLE)
        page.reload()
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")
        page.wait_for_selector("#studioView:not([hidden])")
        assert page.evaluate(read)[0] == "rgb(0, 0, 0)", "the darkness was not remembered"
        context.close()
        browser.close()


def test_more_points_than_fit_page_with_down_then_up_arrows(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    rail = """() => [...document.getElementById('beatRail').children]
                .map((b) => b.classList.contains('beat-arrow') ? b.textContent : Number(b.textContent))"""
    inside = """() => { const r = document.getElementById('beatRail').getBoundingClientRect();
                 return [...document.getElementById('beatRail').children]
                   .every((b) => b.getBoundingClientRect().top >= r.top - 1); }"""
    with sync_playwright() as pw:
        # A very short split-screen half (87px of column): no room to page, so it
        # scrolls - and no number may paint up over the bar above (it did).
        browser, context, page = _open_studio(pw, studio["base"], {"width": 390, "height": 420})
        assert page.evaluate(inside), "numbers paint outside their column"
        assert page.eval_on_selector("#homeButton", TAPPABLE), "the top bar is covered"
        context.close()
        browser.close()

        # A taller half fits a few numbers, so it pages with arrows.
        browser, context, page = _open_studio(pw, studio["base"], {"width": 390, "height": 560})
        first = page.evaluate(rail)
        assert first[-1] == "↓", f"page one should end with a down arrow: {first}"
        assert first[0] == 1 and "↑" not in first, first
        page.click("#beatRail .beat-arrow")
        second = page.evaluate(rail)
        assert second[0] == "↑", f"the top should become an up arrow: {second}"
        assert min(n for n in second if isinstance(n, int)) == first[-2] + 1, (first, second)
        assert page.evaluate(inside)
        for arrow in page.locator("#beatRail .beat-arrow").all():
            assert arrow.evaluate(TAPPABLE), arrow.evaluate(WHAT_COVERS)
        page.click("#beatRail .beat-arrow >> nth=0")
        assert page.evaluate(rail) == first, "the up arrow did not go back"
        context.close()
        browser.close()


def test_six_points_on_a_full_phone_show_five_numbers_then_an_arrow(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _open_studio(pw, studio["base"], PHONE)
        labels = page.evaluate(
            "() => [...document.getElementById('beatRail').children].map((b) => b.textContent)"
        )
        assert labels[:5] == ["1", "2", "3", "4", "5"] and len(labels) == 6, labels
        assert labels[5] not in ("6",), f"the sixth slot must be the arrow: {labels}"
        page.click("#beatRail .beat-arrow")
        after = page.evaluate(
            "() => [...document.getElementById('beatRail').children].map((b) => b.textContent)"
        )
        assert after[1:] == ["6"], f"the next page should hold point 6 under the up arrow: {after}"
        context.close()
        browser.close()
