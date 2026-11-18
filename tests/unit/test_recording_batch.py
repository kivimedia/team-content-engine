"""Start a chosen batch from Today and count actual saved videos on the phone."""
import asyncio
import os
from pathlib import Path

import pytest

from tce.api import dashboard
from tce.api.routers import production
from tests.unit.test_recording_studio_mobile import PHONE, _seed, studio  # noqa: F401
from tests.unit.test_recording_studio_walk_safety import LANDSCAPE_CAMERA, _record

pytest.importorskip("playwright.sync_api")


@pytest.mark.parametrize("finish_early", [False, True])
def test_batch_saves_only_selected_videos(studio, monkeypatch, finish_early):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    monkeypatch.setattr(production.settings, "production_auto_edit", False)
    for rank in (2, 3):
        asyncio.run(_seed(studio["sessionmaker"], rank))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        page = browser.new_page(viewport=PHONE, permissions=["camera", "microphone"])
        page.add_init_script(LANDSCAPE_CAMERA)
        ideas = page.request.get(studio["base"] + "/api/v1/production/recording-queue").json()["ideas"]
        assert len(ideas) == 3
        page.route("**/editorial/today", lambda r: r.fulfill(json={
            "week": {"primary": [dict(i, script_state="ready") for i in ideas]}, "attention": {},
        }))
        page.goto(studio["base"] + "/today")
        page.get_by_text("Record a batch", exact=True).click()
        checks = page.locator(".batch-picker input")
        assert [c.is_checked() for c in checks.all()] == [True, True, False]
        if finish_early:
            checks.nth(0).uncheck()
            expect(page.get_by_role("button", name="Choose at least 2 videos")).to_be_disabled()
        checks.nth(2).check()
        selected = ideas[1:] if finish_early else ideas
        total = len(selected)
        page.get_by_role("button", name=f"Start {total} videos").click()
        for n, idea in enumerate(selected, 1):
            expect(page.locator("#hookViewIdea")).to_have_text(idea["title"])
            page.locator("#hookView .hook-use").first.click()
            _record(page, 3)
            page.locator("#finishSessionButton").click()
            expect(page.locator("#batchProgress")).to_have_text(f"{n} of {total} videos saved", timeout=90000)
            expect(page.locator("#batchPanel")).to_be_visible()
            expect(page.locator("#batchList li").filter(has_text=" · Saved")).to_have_count(n)
            if os.environ.get("TCE_SHOTS"):
                page.screenshot(path=Path(os.environ["TCE_SHOTS"]) / f"batch-{n}-of-{total}.png")
            page.reload()
            expect(page.locator("#batchProgress")).to_have_text(f"{n} of {total} videos saved")
            if finish_early:
                page.get_by_role("button", name="Finish here").click()
                break
            if n < total:
                page.get_by_role("button", name="Record next: " + selected[n]["title"]).click()
            else:
                expect(page.locator("#batchNext")).to_be_hidden()
                page.get_by_role("button", name="Done", exact=True).click()
        expect(page).to_have_url(studio["base"] + "/today")
        assert page.evaluate("sessionStorage.getItem('tce-batch')") is None
        browser.close()
