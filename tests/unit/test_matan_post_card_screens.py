"""Matan's finished-video card in a real browser (decisions 3 and 6, 5-Oct), and the
owner's card unchanged. Synthetic data on a throwaway SQLite file.

His login (a scoped key, Hebrew workspace with idea lanes) sees, on a finished video:
- 'הורדה' (download the finished MP4) and 'העתקה' per platform (copies that post's text),
- no Post, no Schedule button, no owner export,
- no microphone and no 'Back to KM BOT' link (both leave his fence),
- Hebrew only in the post section.

The owner's publish section is compared with a snapshot taken from master's
workspace.js (tests/unit/snapshots/owner_publish_section.html): byte for byte the same
markup. To re-take it: TCE_SNAPSHOT_WORKSPACE_JS=<master's src/tce/api/workspace.js>
TCE_WRITE_OWNER_SNAPSHOT=<path> pytest -k owners_publish_section.

Skipped when Playwright or its Chromium build is not installed.
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tce.api import dashboard
from tce.api.private_access import ScopedEditorGuard
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as ews_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.models.editorial import RecordingUpload, TopicCandidate, VideoPublication
from tce.settings import settings
from tests.editorial_db import create_tables

pytest.importorskip("playwright.sync_api")

OWNER_KEY = "owner-" + uuid.uuid4().hex
MATAN_KEY = "matan-" + uuid.uuid4().hex
WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNER_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
OWNER_UPLOAD = uuid.UUID("0d0d0d0d-1111-4222-8333-444455556666")
MATAN_UPLOAD = uuid.UUID("0e0e0e0e-1111-4222-8333-444455556666")
SNAPSHOT = Path(__file__).parent / "snapshots" / "owner_publish_section.html"
SIZES = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 900}}

HIS_COPY = {
    "instagram": {"caption": "הקהל לא רוצה לשבת. הוא רוצה להיות חלק.\n#מנטליזם #קסם"},
    "facebook": {"message": "פוסט לפייסבוק על אירועים קטנים."},
    "youtube": {"title": "קסם קרוב", "description": "שורה אחת.\n\n#shorts #קסם", "tags": ["קסם", "shorts"]},
    "tiktok": {"caption": "קסם קרוב #קסם"},
}
OWNER_COPY = {
    "instagram": {"caption": "Owner caption #walk"},
    "facebook": {"message": "Owner Facebook post"},
    "youtube": {"title": "Owner title", "description": "Owner description #shorts", "tags": ["walk", "shorts"]},
    "linkedin": {"message": "Owner LinkedIn post", "hashtags": ["ai", "build"]},
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _seed(sm, ws, upload_id, copies):
    async with sm() as s:
        cand = TopicCandidate(
            id=uuid.uuid4(), workspace_id=ws, week_start=datetime(2026, 10, 5), moment_ids=["m"],
            title="קסם קרוב" if ws == WS else "Owner topic", lesson="l", audience="a",
            public_angle="p", gates={}, status="recorded",
        )
        s.add(cand)
        await s.flush()
        s.add(RecordingUpload(
            id=upload_id, workspace_id=ws, candidate_id=cand.id, original_filename="w.mp4",
            storage_path="/tmp/w.mp4", sha256=upload_id.hex * 2, status="edited",
            edited_path="/tmp/w-edited.mp4", created_at=datetime(2026, 10, 5, 9, 0),
        ))
        await s.flush()
        for platform, copy in copies.items():
            s.add(VideoPublication(workspace_id=ws, upload_id=upload_id, candidate_id=cand.id,
                                   platform=platform, status="draft", copy=copy))
        await s.commit()


@pytest.fixture
def server(monkeypatch, tmp_path, request):
    who = request.param
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(OWNER_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{WS}"))
    monkeypatch.setattr(settings, "workspace_languages", f"{WS}:he")
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{WS}:performer", raising=False)
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    if os.environ.get("TCE_SNAPSHOT_WORKSPACE_JS"):
        # Taking the snapshot: serve another tree's workspace.js (master's).
        monkeypatch.setattr(dashboard, "_WORKSPACE_JS_PATH", Path(os.environ["TCE_SNAPSHOT_WORKSPACE_JS"]))
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'card.db').as_posix()}", poolclass=NullPool)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare():
        await create_tables(engine)
        await _seed(sm, WS, MATAN_UPLOAD, HIS_COPY)
        await _seed(sm, OWNER_WS, OWNER_UPLOAD, OWNER_COPY)

    asyncio.run(prepare())
    monkeypatch.setattr(prod, "session_factory", lambda: sm)
    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(prod.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.include_router(ews_router.router, prefix="/api/v1")
    app.include_router(ews_router.production_router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sm
    if hasattr(ews_router, "get_editorial_sessionmaker"):
        app.dependency_overrides[ews_router.get_editorial_sessionmaker] = lambda: sm

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    app.add_middleware(ScopedEditorGuard)
    key = MATAN_KEY if who == "matan" else OWNER_KEY
    seen: list[tuple[str, int]] = []

    async def proxy(scope, receive, send):
        if scope["type"] == "http":
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", key.encode()))
            scope = dict(scope, headers=headers)

            async def recording_send(message):
                if message["type"] == "http.response.start":
                    seen.append((scope["path"], message["status"]))
                await send(message)

            return await app(scope, receive, recording_send)
        await app(scope, receive, send)

    import uvicorn

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(proxy, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("server did not start")
    try:
        yield {"base": f"http://127.0.0.1:{port}", "seen": seen}
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


def _browser(pw):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return pw.chromium.launch(headless=True)
    except PlaywrightError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Chromium is not installed for Playwright: {exc}")


def _shots(tmp_path: Path) -> Path:
    out = Path(os.environ.get("TCE_SHOT_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


CARD_JS = """
() => {
  const sec = document.querySelector('.publish');
  const vis = (el) => !!el && el.getBoundingClientRect().width > 0 && getComputedStyle(el).display !== 'none'
      && getComputedStyle(el).visibility !== 'hidden';
  const text = (el) => (el.textContent || '').trim();
  const english = [];
  const walker = document.createTreeWalker(sec, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const el = n.parentElement;
    if (!el || el.closest('textarea, input, [hidden]') || !vis(el)) continue;
    const t = (n.nodeValue || '').replace(/\\b(TCE|MP4|Instagram|Facebook|YouTube|TikTok|Reel|Page|Short)\\b/g, '').trim();
    if (/[A-Za-z]{3,}/.test(t)) english.push(t.slice(0, 120));
  }
  return {
    post: sec.querySelectorAll('[data-pub-post]').length,
    schedule: sec.querySelectorAll('[data-pub-schedule]').length,
    when: sec.querySelectorAll('.pub-when').length,
    picks: sec.querySelectorAll('[data-pub-pick]').length,
    download: [...sec.querySelectorAll('a[download]')].map((a) => [text(a), a.getAttribute('href')]),
    copy: [...sec.querySelectorAll('[data-pub-copy]')].map((b) => [text(b), b.getAttribute('data-pub-copy')]),
    mic: vis(document.getElementById('talkHeader')),
    kmbot: vis(document.querySelector('.kmbot-link')),
    talkFab: vis(document.getElementById('talkFab')),
    english,
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
    dir: document.documentElement.dir,
  };
}
"""


@pytest.mark.parametrize("server", ["matan"], indirect=True)
@pytest.mark.parametrize("size", ["phone", "desktop"])
def test_his_finished_video_card_downloads_and_copies_and_never_posts(server, tmp_path, size):
    from playwright.sync_api import sync_playwright

    shots = _shots(tmp_path)
    with sync_playwright() as pw:
        browser = _browser(pw)
        context = browser.new_context(viewport=SIZES[size], device_scale_factor=2, locale="he-IL",
                                      is_mobile=size == "phone", has_touch=size == "phone")
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server["base"])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{server['base']}/library")
        page.wait_for_selector(".publish [data-pub-copy]")
        page.wait_for_timeout(600)
        got = page.evaluate(CARD_JS)
        page.locator(".publish").scroll_into_view_if_needed()
        page.screenshot(path=str(shots / f"matan-post-card-{size}.png"), full_page=True)
        assert got["dir"] == "rtl" and not got["overflowX"], got
        assert got["post"] == got["schedule"] == got["when"] == got["picks"] == 0, got
        assert got["download"] == [["הורדה", f"/api/v1/production/uploads/{MATAN_UPLOAD}/edited?download=1"]], got
        assert [c[1] for c in got["copy"]] == ["instagram", "facebook", "youtube", "tiktok"], got
        assert all(c[0] == "העתקה" for c in got["copy"]), got
        assert got["mic"] is False and got["kmbot"] is False and got["talkFab"] is False, got
        assert got["english"] == [], got

        # העתקה puts exactly that post's text on the clipboard, and says so in Hebrew.
        page.click('[data-pub-copy="instagram"]')
        page.wait_for_function("document.querySelector('[data-pub-copy=instagram]').textContent.trim() === 'הועתק'")
        assert page.evaluate("navigator.clipboard.readText()") == HIS_COPY["instagram"]["caption"]
        page.click('[data-pub-copy="youtube"]')
        page.wait_for_timeout(200)
        yt = page.evaluate("navigator.clipboard.readText()")
        assert yt == "קסם קרוב\n\nשורה אחת.\n\n#shorts #קסם\n\nקסם, shorts", yt
        browser.close()
    assert not errors, errors
    assert all(status != 403 for _, status in server["seen"]), server["seen"]


@pytest.mark.parametrize("server", ["owner"], indirect=True)
def test_the_owners_publish_section_is_unchanged(server, tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _browser(pw)
        page = browser.new_context(viewport=SIZES["desktop"]).new_page()
        page.goto(f"{server['base']}/library")
        page.wait_for_selector(".publish [data-pub-post]")
        html = page.evaluate("document.querySelector('.publish').outerHTML")
        mic = page.evaluate("getComputedStyle(document.getElementById('talkHeader')).display")
        kmbot = page.evaluate("getComputedStyle(document.querySelector('.kmbot-link')).display")
        browser.close()
    out = os.environ.get("TCE_WRITE_OWNER_SNAPSHOT")
    if out:
        Path(out).write_text(html, encoding="utf-8")
        pytest.skip(f"snapshot written to {out}")
    assert html == SNAPSHOT.read_text(encoding="utf-8")
    assert re.search(r"Post the ticked ones now", html)
    assert mic != "none" and kmbot != "none"
