"""A solo take earns one celebration after the server saves it, then one tap starts the next take."""

from pathlib import Path
from urllib.parse import urlsplit

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
ASSETS = Path(__file__).resolve().parents[2] / "src" / "tce" / "api"


def test_solo_success_retry_and_next_take():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        context = browser.new_context(viewport={"width": 390, "height": 844}, permissions=["camera", "microphone"])
        page = context.new_page()
        talks = []
        accept = False

        def serve(route):
            path = urlsplit(route.request.url).path
            if path == "/record/solo":
                route.fulfill(path=ASSETS / "recording-solo.html", content_type="text/html")
            elif path in {"/recording.css", "/recording-solo.js", "/take-reward.js"}:
                route.fulfill(path=ASSETS / path[1:])
            elif path.endswith("/agent-talks"):
                talk_id = f"take-{len(talks) + 1}"
                talks.append(talk_id)
                route.fulfill(json={"talk_id": talk_id, "title": "A fresh take"})
            elif path.endswith("/finish"):
                if accept:
                    route.fulfill(json={"talk_id": talks[-1], "upload_id": "video-1", "title": "A fresh take", "edit_started": True})
                else:
                    route.fulfill(status=503, json={"detail": "Temporarily offline"})
            else:
                route.fulfill(json={})

        page.route("https://studio.test/**", serve)
        page.goto("https://studio.test/record/solo")
        page.locator("#soloRecord").click()
        page.locator("#soloFlag").wait_for()
        page.wait_for_timeout(400)
        page.locator("#soloDone").click()
        page.wait_for_function("document.querySelector('#soloStatus').textContent.includes('Trying again')")
        assert page.locator(".take-confetti").count() == 0
        assert page.evaluate("localStorage.getItem('tce-celebrated-takes')") is None

        accept = True
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.locator(".take-confetti").wait_for()
        assert page.evaluate("JSON.parse(localStorage.getItem('tce-celebrated-takes'))") == ["take-1"]
        page.evaluate("TCETakeReward.show('take-1', document.querySelector('#soloStatus'))")
        assert page.locator(".take-confetti").count() == 1
        page.locator(".take-confetti").wait_for(state="detached")
        page.emulate_media(reduced_motion="reduce")
        page.evaluate("TCETakeReward.show('reduced', document.querySelector('#soloStatus'))")
        assert page.locator(".take-confetti").count() == 0
        assert "Library" in page.locator("#soloStatus").inner_text()

        page.get_by_role("button", name="Record another").click()
        page.locator("#soloFlag").wait_for()
        assert talks == ["take-1", "take-2"]
        assert page.locator("#soloRecord").is_disabled()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        browser.close()
