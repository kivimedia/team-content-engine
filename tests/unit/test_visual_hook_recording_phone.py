"""Phone-width proof that the recording screen shows the visual hook picked for the
video (T-25711): the clip, the hook's name and two or three lines on where to
stand, hands and body, and when to move. Real pages and routers on a throwaway
SQLite file, headless Chromium at 390x844 with a fake camera. Synthetic data."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api import dashboard
from tce.api.routers import content_runs as content_runs_router
from tce.api.routers import editorial as editorial_router
from tce.api.routers import hooks as hooks_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.hooks import catalog, library
from tce.settings import settings
from tests.editorial_db import create_tables
from tests.unit.test_recording_studio_mobile import KEY, PHONE, WS, _free_port, _seed

pytest.importorskip("playwright.sync_api")


@pytest.fixture
def studio(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(WS))
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_google_export", "off")
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'studio.db').as_posix()}", poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare():
        await create_tables(engine)
        return await _seed(sessionmaker)

    seeded = asyncio.run(prepare())
    monkeypatch.setattr(prod, "session_factory", lambda: sessionmaker)
    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(prod.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.include_router(content_runs_router.router, prefix="/api/v1")
    app.include_router(hooks_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker

    async def _db():
        async with sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db

    async def proxy(scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/v1/"):
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", KEY.encode()))
            scope = dict(scope, headers=headers)
        await app(scope, receive, send)

    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(proxy, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("recorder server did not start")
    try:
        yield {"base": f"http://127.0.0.1:{port}", **seeded}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


MEASURE = """
() => {
  const r = (el) => el.getBoundingClientRect();
  const sheet = document.getElementById('visualHookSheet');
  const line = document.getElementById('visualHook');
  const heading = document.querySelector('.script-heading');
  const kids = [...sheet.querySelectorAll('video, h2, p, li, button, .visual-hook-label')].filter((e) => r(e).width);
  const overlaps = [];
  for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) {
    const a = r(kids[i]), b = r(kids[j]);
    if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push(kids[i].tagName + '/' + kids[j].tagName);
  }
  const clip = document.getElementById('visualHookClip');
  const how = document.getElementById('visualHookHow');
  const ready = document.getElementById('visualHookReady');
  const hb = r(heading), lb = r(line), howb = r(how);
  const texty = [...sheet.querySelectorAll('h2, p, li, button, .visual-hook-label'), ...line.querySelectorAll('span, strong, button')];
  return {
    sheetOpen: !sheet.hidden,
    lineShown: !line.hidden,
    sheetTitle: document.getElementById('visualHookSheetTitle').textContent,
    lineText: line.querySelector('.visual-hook-line').textContent,
    coach: [...document.querySelectorAll('#visualHookCoach li')].map((li) => li.textContent),
    tip: document.getElementById('cameraHookTip').hidden ? null : document.getElementById('cameraHookTip').textContent,
    clipReady: clip.readyState, clipW: clip.videoWidth, clipErr: clip.error && clip.error.code, clipSrc: clip.getAttribute('src'),
    clipPaused: clip.paused,
    smallest: Math.min(...texty.filter((e) => r(e).width).map((e) => parseFloat(getComputedStyle(e).fontSize))),
    overlaps,
    sheetCovers: !sheet.hidden && r(sheet).top <= 0 && r(sheet).height >= innerHeight - 1 && getComputedStyle(sheet).backgroundColor !== 'rgba(0, 0, 0, 0)',
    readyBottom: sheet.hidden ? 0 : r(ready).bottom + sheet.scrollTop,
    readyH: r(ready).height,
    // the reminder line must sit wholly inside the visible part of the script heading
    lineInside: line.hidden || (lb.top >= hb.top - 1 && lb.bottom <= hb.bottom + 1 && lb.right <= hb.right + 1),
    howH: howb.height,
    overflowX: document.documentElement.scrollWidth > innerWidth + 1,
  };
}
"""


def _open(page, base, cid):
    # The opening was already chosen for this version, so the studio opens straight away.
    page.add_init_script(f"localStorage.setItem('tce-hook-chosen-{cid}-v1', '1')")
    page.goto(f"{base}/record")
    page.wait_for_selector(".idea-card")
    page.click(".idea-card")
    page.wait_for_selector("#studioView:not([hidden])")


def test_phone_recording_screen_coaches_the_picked_hook(studio, tmp_path):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    cid = studio["candidate_id"]
    week = hooks_router._week_key()
    lineup = {"primary": [{"candidate_id": cid, "title": "Plan the course", "filmed": False}], "reserve": []}
    asyncio.run(library.pick(WS, week, "big-number", lineup, cid))
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        except PlaywrightError as exc:  # pragma: no cover
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        context = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True, permissions=["camera", "microphone"])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _open(page, studio["base"], cid)
        # First time on this video: the hook's own screen, before the studio.
        page.wait_for_selector("#visualHookSheet:not([hidden])")
        page.wait_for_function("document.getElementById('visualHookClip').readyState >= 1", timeout=10000)
        m = page.evaluate(MEASURE)
        page.screenshot(path=str(tmp_path / "visual-hook-sheet-390.png"))
        coach = list(catalog.BY_ID["big-number"].coach)
        assert m["sheetOpen"] and m["sheetCovers"], m
        assert m["sheetTitle"] == "Big number" and m["coach"] == coach, m
        assert m["clipSrc"] == "/api/v1/hooks/big-number/preview" and m["clipW"] == 540 and not m["clipErr"], m
        assert m["clipPaused"] is False, m
        assert m["smallest"] >= 15 and not m["overlaps"] and not m["overflowX"], m
        assert m["readyH"] >= 44, m
        page.tap("#visualHookReady")
        page.wait_for_selector("#visualHookSheet", state="hidden")
        m = page.evaluate(MEASURE)
        page.screenshot(path=str(tmp_path / "visual-hook-studio-390.png"))
        assert m["lineShown"] and m["lineText"] == "Visual hook: Big number", m
        assert m["lineInside"] and m["howH"] >= 44 and m["clipPaused"] is True, m
        assert m["tip"] == "Visual hook: Big number. " + coach[0], m
        # How to film it opens the screen again.
        page.tap("#visualHookHow")
        page.wait_for_selector("#visualHookSheet:not([hidden])")
        page.tap("#visualHookReady")
        page.wait_for_selector("#visualHookSheet", state="hidden")
        assert not errors, errors
        # Seen once: opening the same video again goes straight to the studio, line kept.
        page.reload()
        page.wait_for_selector(".idea-card")
        page.click(".idea-card")
        page.wait_for_selector("#visualHook:not([hidden])")
        page.wait_for_timeout(500)
        assert page.evaluate(MEASURE)["sheetOpen"] is False
        context.close()

        # Another video with no hook picked shows nothing.
        context = browser.new_context(viewport=PHONE, is_mobile=True, has_touch=True, permissions=["camera", "microphone"])
        page = context.new_page()
        library.write_store(WS, {"favorites": [], "weeks": {}})  # sync: playwright holds the loop
        _open(page, studio["base"], cid)
        page.wait_for_timeout(800)
        m = page.evaluate(MEASURE)
        assert m["lineShown"] is False and m["sheetOpen"] is False and m["tip"] is None, m
        browser.close()
