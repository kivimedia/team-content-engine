"""The script list is asked for while the studio's scripts are still downloading. Synthetic data.

27-Oct (Angel's QA of Connie's video app): "the record page loads a bit slow". Timed
from far away (250 ms each way, 6 Mbps), the list was only asked for once the 83 KB
recording.js had arrived: a third of the 1.6 s it took the scripts to show.
"""

from __future__ import annotations

import time

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture

pytest.importorskip("playwright.sync_api")


def test_the_script_list_is_asked_for_before_the_studio_scripts_arrive(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})

        def slow_script(route):
            # A phone far from the server: the big script takes a while to come.
            time.sleep(1.5)
            route.continue_()

        page.route("**/recording.js", slow_script)
        page.goto(f"{studio['base']}/record")
        page.wait_for_selector(".idea-card")
        # The browser's own clock: Playwright's events wait while the route sleeps.
        timing = page.evaluate("""() => {
          const all = performance.getEntriesByType('resource');
          const lists = all.filter((e) => e.name.includes('/recording-queue'));
          const script = all.find((e) => new URL(e.name).pathname.endsWith('/recording.js'));
          return {lists: lists.length, listAsked: lists[0].startTime, scriptArrived: script.responseEnd};
        }""")
        assert timing["lists"] == 1, f"the list was asked for {timing['lists']} times, not once"
        assert timing["listAsked"] < timing["scriptArrived"] - 1000, f"the list still waited for recording.js: {timing}"
        browser.close()


def test_a_failed_early_ask_is_asked_again(studio):  # noqa: F811
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        calls = []

        def first_one_fails(route):
            calls.append(route.request.url)
            if len(calls) == 1:
                route.abort()
            else:
                route.continue_()

        page.route("**/recording-queue*", first_one_fails)
        page.goto(f"{studio['base']}/record")
        page.wait_for_selector(".idea-card")
        assert len(calls) == 2, calls
        assert "Could not load" not in page.inner_text("#syncState")
        browser.close()
