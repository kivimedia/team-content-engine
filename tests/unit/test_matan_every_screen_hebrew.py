"""Every screen of the Hebrew login in a real browser, phone and desktop: Hebrew only.

6-Oct (Ziv, from Matan's /today at 390px): "Find more ideas", "Nothing chosen yet" and
the subscription banner were English, and the banner printed the provider's raw text
twice plus an ISO time. This walks every screen his login reaches, on a full week and
on an empty one, and fails on any visible Latin word (text, aria-label, title,
placeholder) beyond an allowlist of product and platform names. The capacity banner
must be one Hebrew line with the resume time in Israel time.

Boots the real pages and routers on a throwaway SQLite file behind a fake proxy that
injects a scoped editor key (his login), like test_hebrew_studio_screens.py. Writes
screenshots and the leak list to TCE_SHOT_DIR when set. Synthetic data only.

Skipped when Playwright or its Chromium build is not installed.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
from tce.api.routers import llm_jobs as llm_jobs_router
from tce.api.routers import production as prod
from tce.db.session import get_db
from tce.editorial.common import packet_key_text
from tce.editorial.lineup import week_start_for
from tce.llm import LLMRequest
from tce.llm import queue as llm_queue
from tce.models.content_run import WorkerGroupState
from tce.models.editorial import RecordingPacket, RecordingUpload, TopicCandidate, VideoPublication
from tce.models.editorial_workspace import WeeklyLineup, WeeklyLineupItem
from tce.models.jennifer import EditorRule
from tce.settings import settings
from tests.editorial_db import create_tables
from tests.unit.test_editorial_packets import good_output

pytest.importorskip("playwright.sync_api")

API = Path(dashboard.__file__).parent
NODE = shutil.which("node")
OWNER_KEY = "owner-" + uuid.uuid4().hex
MATAN_KEY = "matan-" + uuid.uuid4().hex
WS = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNER_WS = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
SIZES = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 900}}
# The live banner of 6-Oct: the provider's own words, twice.
PROVIDER = "You've hit your weekly limit · resets Oct 8, 1am (Asia/Jerusalem)"
PARK = (datetime.now(UTC) + timedelta(days=2)).replace(tzinfo=None, minute=0, second=0, microsecond=0)
HE_DAYS = ["ב'", "ג'", "ד'", "ה'", "ו'", "שבת", "א'"]  # Monday first, like weekday()


def expected_capacity_line(retry_at_utc: datetime) -> str:
    local = retry_at_utc.replace(tzinfo=UTC).astimezone(ZoneInfo("Asia/Jerusalem"))
    return (f"המערכת בהפסקה קצרה וחוזרת לעבוד ביום {HE_DAYS[local.weekday()]} "
            f"{local.day}.{local.month} בשעה {local:%H:%M}")


# Visible Latin words on his screens. Only these names may stay in Latin letters.
LEAK_JS = r"""
() => {
  const allowed = /\b(TCE|KM BOT|KM|BOT|AI|Instagram|Facebook|YouTube|TikTok|LinkedIn|Reels?|Shorts?|MP4)\b/g;
  const vis = (el) => {
    if (!el || el.closest('[hidden]')) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const latin = (s) => /[A-Za-z]{2,}/.test(String(s || '').replace(allowed, ''));
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const el = node.parentElement;
    if (!el || el.closest('script, style, textarea, input') || !vis(el)) continue;
    if (latin(node.nodeValue)) out.push((node.nodeValue || '').trim().slice(0, 200));
  }
  document.querySelectorAll('[aria-label], [title], [placeholder]').forEach((el) => {
    if (!vis(el)) return;
    ['aria-label', 'title', 'placeholder'].forEach((a) => {
      const v = el.getAttribute(a);
      if (v && latin(v)) out.push(a + ': ' + v.slice(0, 200));
    });
  });
  if (latin(document.title)) out.push('title: ' + document.title);
  return Array.from(new Set(out));
}
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _candidate(title: str, status: str = "selected", **kw) -> TopicCandidate:
    return TopicCandidate(
        id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None),
        moment_ids=[str(uuid.uuid4())], title=title,
        lesson="מה קורה לקהל, לא מה קורה לקלף.", audience="מארגני אירועים",
        reasons_to_care=["זה מה שהם זוכרים"], public_angle="הרגע של הקהל.",
        gates={}, citations_private=[], status=status, origin="selector",
        freshness_role="evergreen", rank=1, **kw,
    )


async def _seed(sm, full: bool, tmp_path: Path) -> dict:
    out: dict = {}
    async with sm() as s:
        # The subscription is at its limit until PARK (the 6-Oct banner).
        s.add(WorkerGroupState(group_key=llm_queue.WORKER_GROUP_KEY, state="waiting_capacity",
                               retry_at=PARK, reason=f"{PROVIDER} {PROVIDER}"))
        lineup = WeeklyLineup(id=uuid.uuid4(), workspace_id=WS, week_start=week_start_for(None),
                              primary_slots=5)
        s.add(lineup)
        await s.flush()
        if not full:
            await s.commit()
            return out

        ready = _candidate("הרגע שהקלף מתהפך")
        bare = _candidate("למה אני מסתכל על הידיים של הקהל")
        spare = _candidate("סלון מול במה")
        waiting = _candidate("השאלה שאני שואל לפני כל ערב", status="candidate")
        filmed = _candidate("קסם קרוב", status="recorded")
        s.add_all([ready, bare, spare, waiting, filmed])
        await s.flush()
        output = good_output()
        hooks = output["hook_options"]
        for h, text in zip(hooks, ("אתם יודעים מה הכי מפחיד אנשים?", "הקלף הוא לא הקסם.",
                                   "פעם חשבתי שהקהל מסתכל על הידיים שלי."), strict=False):
            h["text"] = text
            h["question"] = "מה מפחיד אותם?"
            h["rationale"] = "פותח בשאלה שכל אחד מכיר."
        # Beat names are script content: his packets are written in Hebrew.
        for beat, label in zip(output["beats"], ("תוצאה", "שאלה", "בעיות", "סדר", "שיעורים"), strict=False):
            beat["label"] = label
        packet = RecordingPacket(
            id=uuid.uuid4(), workspace_id=WS, candidate_id=ready.id, version=1,
            bullets=["מה קורה לאנשים ברגע שהקלף מתהפך.", "למה אני מסתכל על הידיים של הקהל."],
            script_phrases=["אתם יודעים מה הכי מפחיד אנשים?", "לא הקלף עצמו.", "זה כל הסיפור."],
            facebook_post="פוסט לפייסבוק", linkedin_post="", interviewer_prompt="שאלה",
            hook_options=hooks, selected_hook_id=output["selected_hook_id"], beats=output["beats"],
            citations_private=[], public_safety={"status": "clean", "issues": []}, status="ready",
        )
        s.add(packet)
        for rank, (cand, slot) in enumerate(((ready, "primary"), (bare, "primary"), (spare, "reserve")), 1):
            s.add(WeeklyLineupItem(id=uuid.uuid4(), workspace_id=WS, lineup_id=lineup.id,
                                   candidate_id=cand.id, rank=rank, slot=slot, lane="other",
                                   status="planned"))
        edited = tmp_path / "edited.mp4"
        edited.write_bytes(b"\x00" * 64)
        upload = RecordingUpload(
            id=uuid.uuid4(), workspace_id=WS, candidate_id=filmed.id, original_filename="w.mp4",
            storage_path=str(edited), sha256=uuid.uuid4().hex * 2, status="edited",
            edited_path=str(edited), created_at=datetime(2026, 10, 5, 9, 0),
            # A stamped render, so the notes sheet opens on it.
            render_ref="r1", rendered_keep=[[0.0, 6.0]], edit_plan={"keep": [[0.0, 6.0]]},
        )
        raw = RecordingUpload(
            id=uuid.uuid4(), workspace_id=WS, candidate_id=filmed.id, original_filename="r.mp4",
            storage_path=str(edited), sha256=uuid.uuid4().hex * 2, status="uploaded",
            created_at=datetime(2026, 10, 5, 10, 0),
        )
        s.add_all([upload, raw])
        await s.flush()
        for platform, copy in {"instagram": {"caption": "הקהל רוצה להיות חלק."},
                               "facebook": {"message": "פוסט לפייסבוק."},
                               "youtube": {"title": "קסם קרוב", "description": "שורה.", "tags": ["קסם"]},
                               "tiktok": {"caption": "קסם קרוב"}}.items():
            s.add(VideoPublication(workspace_id=WS, upload_id=upload.id, candidate_id=filmed.id,
                                   platform=platform, status="draft", copy=copy))
        # A script asked for during the limit: it waits for PARK and says so.
        nonce = str(uuid.uuid4())
        job = await llm_queue.enqueue(s, LLMRequest(
            job_type="recording_packet", agent_name="recording_packet_writer",
            messages=[{"role": "user", "content": f"PACKET REQUEST: {nonce}\n\nIDEA"}],
            workspace_id=WS, run_id=bare.id, idempotency_key=packet_key_text(WS, nonce)))
        job.status, job.error_code, job.retry_at = "waiting_capacity", "capacity", PARK
        s.add(EditorRule(workspace_id=WS, text="לחתוך כל פנייה לכלבים.", source_upload_id=upload.id,
                         times_applied=2, applied_uploads=[]))
        await s.commit()
        out.update(candidate=str(ready.id), packet=str(packet.id), upload=str(upload.id))
    return out


@pytest.fixture
def server(monkeypatch, tmp_path, request):
    full = request.param == "full"
    monkeypatch.setattr(settings, "private_access_key", SecretStr(OWNER_KEY))
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(OWNER_WS))
    monkeypatch.setattr(settings, "editor_workspace_keys", SecretStr(f"{MATAN_KEY}:{WS}"))
    monkeypatch.setattr(settings, "workspace_languages", f"{WS}:he")
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{WS}:performer", raising=False)
    monkeypatch.setattr(settings, "evidence_upload_dir", str(tmp_path / "rec"))
    monkeypatch.setattr(settings, "production_google_export", "off")

    async def enabled():
        return True

    async def no_workers():
        return {"workers": [], "latest": None}

    monkeypatch.setattr(dashboard, "_workspace_enabled", enabled)
    # No desktop worker reports here (the live status file is never read).
    monkeypatch.setattr(llm_jobs_router, "get_worker_status", no_workers)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'he.db').as_posix()}",
                                 poolclass=NullPool)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def prepare():
        await create_tables(engine)
        return await _seed(sm, full, tmp_path)

    seeded = asyncio.run(prepare())
    monkeypatch.setattr(prod, "session_factory", lambda: sm)
    app = FastAPI()
    app.include_router(dashboard.router)
    app.include_router(prod.router, prefix="/api/v1")
    app.include_router(editorial_router.router, prefix="/api/v1")
    app.include_router(ews_router.router, prefix="/api/v1")
    app.include_router(ews_router.production_router, prefix="/api/v1")
    app.include_router(content_runs_router.router, prefix="/api/v1")
    app.dependency_overrides[editorial_router.get_editorial_sessionmaker] = lambda: sm
    if hasattr(ews_router, "get_editorial_sessionmaker"):
        app.dependency_overrides[ews_router.get_editorial_sessionmaker] = lambda: sm

    async def _db():
        async with sm() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_db] = _db
    app.add_middleware(ScopedEditorGuard)

    async def proxy(scope, receive, send):
        if scope["type"] == "http":
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", MATAN_KEY.encode()))
            scope = dict(scope, headers=headers)
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
        yield {"base": f"http://127.0.0.1:{port}", "full": full, **seeded}
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        asyncio.run(engine.dispose())


def _shots(tmp_path: Path) -> Path:
    out = Path(os.environ.get("TCE_SHOT_DIR") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.mark.parametrize("server", ["full", "empty"], indirect=True)
@pytest.mark.parametrize("size", ["phone", "desktop"])
def test_every_screen_of_his_login_is_hebrew(server, tmp_path, size):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    shots = _shots(tmp_path)
    base = server["base"]
    kind = "full" if server["full"] else "empty"
    leaks: dict[str, list[str]] = {}
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        except PlaywrightError as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Chromium is not installed for Playwright: {exc}")
        context = browser.new_context(viewport=SIZES[size], device_scale_factor=1, locale="he-IL",
                                      timezone_id="Asia/Jerusalem", is_mobile=size == "phone",
                                      has_touch=size == "phone", permissions=["camera", "microphone"])
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def check(name: str, settle: int = 900):
            page.wait_for_timeout(settle)
            assert page.evaluate("document.documentElement.dir") == "rtl", name
            found = page.evaluate(LEAK_JS)
            if found:
                leaks[name] = found
            # Written as it goes, so a screen that fails to open still leaves the list.
            (shots / f"he-every-{kind}-leaks-{size}.json").write_text(
                json.dumps(leaks, ensure_ascii=False, indent=1), encoding="utf-8")
            page.screenshot(path=str(shots / f"he-every-{kind}-{name}-{size}.png"), full_page=True)

        def visit(path: str, name: str, wait: str | None = None):
            page.goto(base + path)
            page.wait_for_selector(wait or "#view .page-head, #view .empty")
            check(name)

        visit("/today", "today", "#view .next-action")
        # The capacity banner: one Hebrew line, never the provider's text or an ISO time.
        banner = page.locator("#view p.notice").first.text_content().strip()
        if banner != expected_capacity_line(PARK):
            leaks["today-capacity-banner"] = [banner]
        if size == "phone":
            # The bar's Type opens the typed conversation about the week.
            if page.locator("#typeFab").count():
                page.click("#typeFab")
                page.wait_for_selector("#talkSheet:not([hidden])")
                check("today-talk")
                page.click("#talkClose")
        visit("/topics", "topics")
        visit("/week", "week")
        visit("/library", "library")
        visit("/library/rules", "rules")
        visit("/settings", "settings")
        if server["full"]:
            visit(f"/topics/{server['candidate']}", "topic-room", "#view .block")
            visit(f"/scripts/{server['packet']}", "script-outline", "#view [data-wtab]")
            for tab in ("script", "openings", "posts"):
                page.click(f'[data-wtab="{tab}"]')
                page.wait_for_selector(f'[data-wtab="{tab}"][aria-pressed="true"]')
                check(f"script-{tab}")
            page.goto(base + "/library?filter=all")
            page.wait_for_selector(".publish [data-pub-copy]")
            check("library-all")
            page.goto(f"{base}/library/{server['upload']}/talk")
            page.wait_for_selector("#notesSheet:not([hidden])")
            check("notes-sheet", 2500)
            page.goto(base + "/record")
            page.wait_for_selector(".idea-card")
            check("record-queue")
            page.click(".idea-card")
            page.wait_for_selector("#hookView:not([hidden]) .hook-use")
            check("record-openings")
            page.locator("#hookView .hook-option").first.locator(".hook-use").click()
            page.wait_for_selector("#reader .reader-line")
            check("record-points")
            page.click("#scriptTab")
            page.wait_for_function("document.getElementById('reader').classList.contains('script')")
            check("record-script")
        else:
            page.goto(base + "/record")
            page.wait_for_selector("#queueTitle")
            check("record-empty", 1500)
        browser.close()
    (shots / f"he-every-{kind}-leaks-{size}.json").write_text(
        json.dumps(leaks, ensure_ascii=False, indent=1), encoding="utf-8")
    assert leaks == {}, leaks
    assert not errors, errors


# ------------------------------------------------- the capacity line, without a browser

needs_node = pytest.mark.skipif(not NODE, reason="node not installed")


@needs_node
@pytest.mark.parametrize("iso,want", [
    ("2026-10-07T22:00:00Z", "המערכת בהפסקה קצרה וחוזרת לעבוד ביום ה' 8.10 בשעה 01:00"),
    ("2026-10-10T07:30:00Z", "המערכת בהפסקה קצרה וחוזרת לעבוד ביום שבת 10.10 בשעה 10:30"),
    ("2026-12-31T23:15:00", "המערכת בהפסקה קצרה וחוזרת לעבוד ביום ו' 1.1 בשעה 01:15"),
])
def test_capacity_banner_is_one_hebrew_line_in_israel_time(iso, want):
    path = json.dumps(str(API / "i18n-he.js"))
    line = f"Subscription capacity: {PROVIDER} {PROVIDER}; resumes at {iso}"
    out = subprocess.run(
        [NODE, "-e", f"process.stdout.write(JSON.stringify(require({path}).translate({json.dumps(line)})))"],
        check=True, capture_output=True, text=True, timeout=30, env={**os.environ, "TZ": "UTC"},
    ).stdout
    assert json.loads(out) == want
