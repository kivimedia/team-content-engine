"""The Hebrew login's studio and workspace in a real browser, phone and desktop. Synthetic data.

Boots the real pages and routers on a throwaway SQLite file behind a fake proxy
that injects a SCOPED editor key (a Hebrew workspace's own login), then drives
headless Chromium at 390x844 and 1280x900. Asserts the page is right to left with
Hebrew UI, the teleprompter shows one sentence per line in both Points and Full
script, nothing overflows sideways, and no request leaves the workspace. Writes
screenshots to TCE_SHOT_DIR when set (else the test's tmp dir).

Skipped when Playwright or its Chromium build is not installed.
"""

from __future__ import annotations

import json
import asyncio
import os
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
from tce.api.routers import content_runs as content_runs_router
from tce.api.routers import editorial as editorial_router
from tce.api.routers import editorial_workspace as ews_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial.lineup import week_start_for
from tce.models.editorial import RecordingPacket, TopicCandidate
from tce.models.editorial_workspace import WeeklyLineup, WeeklyLineupItem
from tce.settings import settings
from tests.editorial_db import create_tables
from tests.unit.test_editorial_packets import good_output

pytest.importorskip("playwright.sync_api")

OWNER_KEY = "owner-" + uuid.uuid4().hex
MATAN_KEY = "matan-" + uuid.uuid4().hex
WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNER_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
SIZES = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 900}}

BULLETS = [
    "מה באמת קורה לאנשים ברגע שהקלף מתהפך. הם מפסיקים לנשום לשנייה.",
    "למה אני מסתכל על הידיים של הקהל ולא על שלי.",
    "הרגע שבו מישהו צוחק כי הוא לא יודע מה להגיד.",
    "מה ההבדל בין הופעה בסלון לבמה. בסלון אין לאן לברוח!",
    "שאלה אחת שאני שואל את עצמי לפני כל ערב.",
    "מה אני רוצה שיזכרו מחר בבוקר.",
]
PHRASES = [
    "אתם יודעים מה הכי מפחיד אנשים?",
    "לא הקלף עצמו.",
    "הרגע שהם מבינים שהם לא יודעים איך. ואז הם צוחקים.",
    "אני מסתכל על הידיים שלהם, לא על שלי.",
    "בסלון אין לאן לברוח.",
    "אז אני שואל את עצמי שאלה אחת.",
    "מה הם יזכרו מחר בבוקר?",
    "זה כל הסיפור.",
]



# 5-Oct review: the Today screenshot still showed "Record this one" and "Open the topic".
# Every visible control and heading on his screens must be Hebrew; only the product
# names below may stay in Latin letters.
LEAK_JS = r"""
() => {
  const allowed = /\b(KM BOT|TCE|AI|KM|BOT)\b/g;
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const el = node.parentElement;
    if (!el || el.closest('script, style, textarea, input, [hidden]')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    const text = (node.nodeValue || '').replace(allowed, '').trim();
    if (/[A-Za-z]{3,}/.test(text)) out.push((node.nodeValue || '').trim().slice(0, 200));
  }
  return Array.from(new Set(out));
}
"""

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _seed(sessionmaker) -> dict:
    output = good_output()
    hooks = output["hook_options"]
    hooks[0]["text"] = PHRASES[0]
    hooks[1]["text"] = "הקלף הוא לא הקסם. הפנים שלכם הן הקסם."
    hooks[2]["text"] = "פעם חשבתי שהקהל מסתכל על הידיים שלי."
    for h, q in zip(hooks, ("מה מפחיד אותם?", "אז מה כן?", "ועל מה הם מסתכלים?"), strict=True):
        h["question"] = q
        h["rationale"] = "פותח בשאלה שכל אחד מכיר."
    cand = TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=datetime(2026, 10, 5),
        moment_ids=["11111111-1111-1111-1111-111111111111"],
        title="הרגע שהקלף מתהפך", lesson="מה קורה לקהל, לא מה קורה לקלף.",
        audience="קהל", public_angle="הרגע של הקהל.", gates={}, status="selected",
    )
    packet = RecordingPacket(
        id=uuid.uuid4(), workspace_id=WS, candidate_id=cand.id, version=1,
        bullets=BULLETS, script_phrases=PHRASES,
        facebook_post="פוסט", linkedin_post="פוסט", interviewer_prompt="שאלה",
        hook_options=hooks, selected_hook_id=output["selected_hook_id"], beats=output["beats"],
        citations_private=[], public_safety={"status": "clean", "issues": []}, status="ready",
    )
    async with sessionmaker() as s:
        s.add_all([cand, packet])
        lineup = WeeklyLineup(id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None))
        s.add(lineup)
        await s.flush()
        s.add(WeeklyLineupItem(
            id=uuid.uuid4(), workspace_id=WS, lineup_id=lineup.id, candidate_id=cand.id,
            rank=1, slot="primary", lane="other",
        ))
        await s.commit()
    return {"packet_id": str(packet.id)}


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(OWNER_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{WS}"))
    monkeypatch.setattr(settings, "workspace_languages", f"{WS}:he")
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_google_export", "off")

    async def enabled():
        return True

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'he.db').as_posix()}",
                                 poolclass=NullPool)
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
    app.include_router(ews_router.router, prefix="/api/v1")
    app.include_router(ews_router.production_router, prefix="/api/v1")
    app.include_router(content_runs_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sessionmaker
    if hasattr(ews_router, "get_editorial_sessionmaker"):
        app.dependency_overrides[ews_router.get_editorial_sessionmaker] = lambda: sessionmaker

    async def _db():
        async with sessionmaker() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    app.add_middleware(ScopedEditorGuard)
    seen: list[tuple[str, int]] = []

    async def proxy(scope, receive, send):
        # nginx injects the Hebrew login's key on EVERY request after Basic Auth.
        if scope["type"] == "http":
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", MATAN_KEY.encode()))
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
        yield {"base": f"http://127.0.0.1:{port}", "seen": seen, **seeded}
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


STATE_JS = """
() => {
  const vw = window.innerWidth;
  const lines = [...document.querySelectorAll('#reader .reader-line')];
  return {
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
    overflowX: document.documentElement.scrollWidth > vw + 1,
    record: document.getElementById('recordButton')?.firstChild?.textContent?.trim(),
    pointsTab: document.getElementById('pointsTab')?.textContent.trim(),
    scriptTab: document.getElementById('scriptTab')?.textContent.trim(),
    readerDir: lines[0] ? getComputedStyle(lines[0]).direction : null,
    sentenceCounts: lines.map((l) => l.querySelectorAll('.reader-sentence').length),
    labels: lines.map((l) => l.querySelector('.reader-index')?.textContent || ''),
    font: getComputedStyle(document.body).fontFamily,
  };
}
"""


def _shot_dir(tmp_path: Path) -> Path:
    out = Path(os.environ.get("TCE_SHOT_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.mark.parametrize("size", ["phone", "desktop"])
def test_hebrew_studio_and_workspace_render_rtl(server, tmp_path, size):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    shots = _shot_dir(tmp_path)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
            )
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        context = browser.new_context(
            viewport=SIZES[size], device_scale_factor=2,
            is_mobile=size == "phone", has_touch=size == "phone",
            permissions=["camera", "microphone"], locale="he-IL",
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        leaks = {}

        def check(screen):
            found = page.evaluate(LEAK_JS)
            if found:
                leaks[screen] = found

        page.goto(f"{server['base']}/record")
        page.wait_for_selector(".idea-card")
        page.wait_for_function("document.getElementById('queueTitle').textContent === 'מוכן להקלטה'")
        state = page.evaluate(STATE_JS)
        assert state["lang"] == "he" and state["dir"] == "rtl", state
        assert state["overflowX"] is False, state
        assert "Heebo" in state["font"], state
        page.screenshot(path=str(shots / f"he-record-queue-{size}.png"), full_page=True)
        check("record-queue")

        page.click(".idea-card")
        page.wait_for_selector("#hookView:not([hidden]) .hook-use")
        page.screenshot(path=str(shots / f"he-record-openings-{size}.png"), full_page=True)
        check("record-openings")
        page.locator("#hookView .hook-option").first.locator(".hook-use").click()
        page.wait_for_selector("#studioView:not([hidden])")
        page.wait_for_selector("#reader .reader-line")
        state = page.evaluate(STATE_JS)
        assert state["record"] == "הקלטה" and state["pointsTab"] == "נקודות", state
        assert state["scriptTab"] == "תסריט מלא", state
        assert state["readerDir"] == "rtl", state
        # Point 1 has two sentences, so it reads as two lines; labels are Hebrew.
        assert max(state["sentenceCounts"]) >= 2, state
        assert any(lbl.startswith("נקודה") for lbl in state["labels"]), state
        assert state["overflowX"] is False, state
        page.screenshot(path=str(shots / f"he-record-points-{size}.png"))
        check("record-points")

        page.click("#scriptTab")
        page.wait_for_function("document.getElementById('reader').classList.contains('script')")
        state = page.evaluate(STATE_JS)
        assert state["readerDir"] == "rtl" and max(state["sentenceCounts"]) >= 2, state
        page.screenshot(path=str(shots / f"he-record-script-{size}.png"))
        check("record-script")

        page.goto(f"{server['base']}/today")
        page.wait_for_function("document.documentElement.dir === 'rtl'")
        page.wait_for_function(
            "document.querySelector('#bottomNav a[data-route=today]').textContent.includes('היום')"
        )
        page.wait_for_timeout(800)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        check("today")
        page.screenshot(path=str(shots / f"he-today-{size}.png"), full_page=True)

        # His other workspace screens: right to left, no English controls or headings.
        for route in ("topics", "week", "library", "settings"):
            page.goto(f"{server['base']}/{route}")
            page.wait_for_function("document.documentElement.dir === 'rtl'")
            page.wait_for_timeout(1200)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), route
            page.screenshot(path=str(shots / f"he-{route}-{size}.png"), full_page=True)
            check(route)
        # The full list lands next to the screenshots (pytest truncates long diffs).
        (shots / f"he-leaks-{size}.json").write_text(
            json.dumps(leaks, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        assert leaks == {}, leaks
        browser.close()

    assert not errors, errors
    # Every request stayed inside what a client login may reach.
    assert all(status != 403 for _, status in server["seen"]), server["seen"]
