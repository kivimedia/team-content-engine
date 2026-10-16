"""Leaving the studio while a take is still saving. Synthetic data.

12-Oct, Ziv on a call: "I need the saving process to be in the background and not
force me to stay on that page. Like if I click back to go back to TCE ... I don't
want to wait until you save ... move the files with you to another page, continue
with the saving."

So: Stop, Finish, and leave at once for another TCE page. The end of the clip and
the hand-over for editing must still happen, from the page he went to.
"""

from __future__ import annotations

import pytest

from tests.unit.test_recording_studio_mobile import studio  # noqa: F401 - fixture
from tests.unit.test_recording_studio_walk_safety import (
    LANDSCAPE_CAMERA,
    SLOW_CLIP_FINISH,
    _record,
    _studio_page,
)

pytest.importorskip("playwright.sync_api")


def test_leaving_right_after_finish_still_sends_the_take_for_editing(studio, monkeypatch):  # noqa: F811
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard

    # Today is the page he goes back to. Off, it bounces to the studio instead.
    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, SLOW_CLIP_FINISH)
        _record(page, 4)
        # The end of the clip is still on its way, like a long take on a walk.
        page.evaluate("() => { window.__slowFinish = 4000; }")
        page.evaluate(
            "() => { document.getElementById('finishClipButton').click();"
            " setTimeout(() => document.getElementById('finishSessionButton').click(), 300); }"
        )
        page.wait_for_timeout(800)
        # He leaves at once. Nothing on the studio is allowed to hold him.
        page.evaluate("() => { window.__slowFinish = 0; }")
        with context.expect_event(
            "request",
            lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"),
            timeout=30000,
        ) as finished:
            page.goto(f"{studio['base']}/today")
        assert len(finished.value.post_data_json["selected_clip_ids"]) == 1
        # And Today says so, in a line that pushes the page down rather than covering it.
        page.wait_for_function(
            "() => (document.getElementById('tceSavingBar')?.textContent || '')"
            ".startsWith('Your take is saved and on its way to editing.')",
            timeout=10000,
        )
        bar = page.evaluate(
            "() => { const b = document.getElementById('tceSavingBar');"
            " return { position: getComputedStyle(b).position, after: b.previousElementSibling?.tagName }; }"
        )
        assert bar == {"position": "static", "after": "HEADER"}, bar
        assert page.evaluate("() => localStorage.getItem('tce-recording-pending')") == '{"clips":{},"sessions":{}}'
        context.close()
        browser.close()


def test_the_finish_note_goes_on_one_tap(studio):  # noqa: F811
    """The three-second note stays (8-Oct, his ask), but it never holds him."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, context, page = _studio_page(pw, studio["base"], LANDSCAPE_CAMERA, SLOW_CLIP_FINISH)
        _record(page, 3)
        page.evaluate("() => { window.__slowFinish = 4000; }")
        page.click("#finishSessionButton")
        page.wait_for_function("() => document.getElementById('finishDialog').open", timeout=5000)
        assert "You can leave this page" in page.inner_text("#finishDialogNow")
        page.click("#finishDialog")
        page.wait_for_function("() => !document.getElementById('finishDialog').open", timeout=500)
        page.wait_for_selector("#queueView:not([hidden])", timeout=2000)
        # The end of the clip is still on its way, and the list says so without a wall.
        assert "You can leave this page" in page.inner_text("#finishStatusNow")
        with context.expect_event(
            "request", lambda r: "/recording-sessions/" in r.url and r.url.endswith("/finish"), timeout=30000
        ):
            pass
        context.close()
        browser.close()


def test_a_no_script_take_left_after_done_is_sent_from_another_page(studio, monkeypatch):  # noqa: F811
    """Record without a script, Done, leave: Today sends what is left and starts the edit.

    Until 16-Oct the no-script recorder sent its leftover pieces only when its own page
    opened again, so a take he walked away from sat on the phone.
    """
    from playwright.sync_api import sync_playwright

    from tce.api import dashboard

    async def enabled() -> bool:
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)

    seen = []

    def server(route, request):
        seen.append((request.method, request.url.split("/agent-talks/")[1], request.post_data))
        route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.route("**/api/v1/production/agent-talks/**", server)
        page.goto(f"{studio['base']}/today")
        # What the no-script page leaves behind when he presses Done and goes: one piece
        # still to send, and a take marked done.
        page.evaluate(
            """() => new Promise((resolve, reject) => {
              const open = indexedDB.open('tce-solo-v1', 1);
              open.onupgradeneeded = () => {
                open.result.createObjectStore('pieces', { keyPath: 'key' });
                open.result.createObjectStore('takes', { keyPath: 'talkId' });
              };
              open.onerror = () => reject(open.error);
              open.onsuccess = () => {
                const tx = open.result.transaction(['pieces', 'takes'], 'readwrite');
                tx.objectStore('pieces').put({ key: 'talk-1:0', talkId: 'talk-1', sequence: 0,
                  blob: new Blob(['x'], { type: 'video/webm' }), at: 1 });
                tx.objectStore('takes').put({ talkId: 'talk-1', done: true,
                  startedAt: '2026-10-16T08:00:00Z', endedAt: '2026-10-16T08:01:00Z', durationMs: 60000 });
                tx.oncomplete = () => { open.result.close(); resolve(); };
                tx.onerror = () => reject(tx.error);
              };
            })"""
        )
        with page.expect_request(
            lambda r: r.method == "POST" and r.url.endswith("/agent-talks/talk-1/finish"), timeout=15000
        ) as finished:
            page.goto(f"{studio['base']}/today")
        assert finished.value.post_data_json == {
            "ended_at": "2026-10-16T08:01:00Z", "duration_ms": 60000, "edit": True,
        }
        page.wait_for_function(
            "() => (document.getElementById('tceSavingBar')?.textContent || '')"
            ".startsWith('Your take is saved and on its way to editing.')",
            timeout=10000,
        )
        # The piece first, then the finish, once each.
        assert [(m, path) for m, path, _ in seen] == [("PUT", "talk-1/chunks/0"), ("POST", "talk-1/finish")]
        left = page.evaluate(
            """() => new Promise((resolve) => {
              const open = indexedDB.open('tce-solo-v1', 1);
              open.onsuccess = () => {
                const tx = open.result.transaction(['pieces', 'takes'], 'readonly');
                const p = tx.objectStore('pieces').count();
                const t = tx.objectStore('takes').count();
                tx.oncomplete = () => resolve([p.result, t.result]);
              };
            })"""
        )
        assert left == [0, 0]
        context.close()
        browser.close()
