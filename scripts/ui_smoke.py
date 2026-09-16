"""Headless UI smoke test for the dashboard Editorial area. Synthetic data only.

Starts the real TCE app against a throwaway SQLite database, seeds synthetic
candidates, packets, uploads, LLM jobs and collection runs, then drives the
Editorial area with headless Chromium at phone (390x844) and desktop
(1440x900) sizes: opens a card, clicks feedback, saves a note, opens the packet
and the edit plan. Saves PNG screenshots and reports console errors, horizontal
overflow, overlapping interactive elements and small tap targets.

Usage:
    python scripts/ui_smoke.py --out <screenshot dir> [--port 8765]

Requires: pip install playwright && python -m playwright install chromium
Nothing here calls a paid API, publishes, or touches a real database.
"""

# ruff: noqa: E501  (embedded browser JS and synthetic seed rows)
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

WORK = Path(tempfile.mkdtemp(prefix="tce-ui-smoke-"))
WS = uuid.UUID("abcdef00-0000-4000-8000-00000000abcd")
EDITOR_KEY = "ui-smoke-" + uuid.uuid4().hex  # throwaway, lives only in this process

# Environment must be set before any tce import.
os.environ["TCE_DATABASE_URL"] = f"sqlite+aiosqlite:///{(WORK / 'smoke.db').as_posix()}"
os.environ["TCE_PRIVATE_ACCESS_KEY"] = EDITOR_KEY
os.environ["TCE_EDITOR_DEFAULT_WORKSPACE_ID"] = str(WS)
os.environ["TCE_EVIDENCE_UPLOAD_DIR"] = str(WORK / "recordings")
os.environ["TCE_VIDEO_OUTPUT_DIR"] = str(WORK / "video")
os.environ["TCE_IMAGE_STORAGE_DIR"] = str(WORK / "images")
os.environ["TCE_DISABLE_SCHEDULER"] = "1"
os.environ["TMP"] = os.environ["TEMP"] = str(WORK)  # worker-status file stays throwaway
tempfile.tempdir = str(WORK)

sqlite3.register_adapter(list, json.dumps)
sqlite3.register_adapter(dict, json.dumps)

from sqlalchemy.dialects.postgresql import ARRAY, JSONB  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _array_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _pguuid_sqlite(type_, compiler, **kw):
    return "TEXT"


def _json_processors(cls):
    orig_bind, orig_result = cls.bind_processor, cls.result_processor

    def bind(self, dialect):
        if dialect.name == "sqlite":
            return lambda v: json.dumps(v) if v is not None else None
        return orig_bind(self, dialect)

    def result(self, dialect, coltype):
        if dialect.name == "sqlite":

            def process(v):
                if isinstance(v, str):
                    try:
                        return json.loads(v)
                    except ValueError:
                        return v
                return v

            return process
        return orig_result(self, dialect, coltype)

    cls.bind_processor, cls.result_processor = bind, result


_json_processors(JSONB)
_json_processors(ARRAY)

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import tce.db.session as session_mod  # noqa: E402

engine = create_async_engine(os.environ["TCE_DATABASE_URL"])
session_mod.engine = engine
session_mod.async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _smoke_get_db():
    async with session_mod.async_session() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


def _monday(d: date) -> datetime:
    m = d - timedelta(days=d.weekday())
    return datetime(m.year, m.month, m.day)


async def seed() -> dict:
    import tce.models  # noqa: F401
    from tce.db.base import Base
    from tce.models.editorial import (
        EditorialFeedback,
        EvidenceCollectionRun,
        RecordingPacket,
        RecordingUpload,
        TopicCandidate,
    )
    from tce.models.llm_job import LLMJob
    from tce.production.retakes import plan_edit

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    week = _monday(date.today())
    now = datetime.now(UTC).replace(tzinfo=None)
    gates_ok = {
        "small_service_business": {
            "pass": True,
            "reason": "A two-person studio doing its own intake.",
        },
        "coach_or_event_owner_relevance": {
            "pass": True,
            "reason": "Event owners answer the same inquiries.",
        },
        "concrete_supported_substance": {
            "pass": True,
            "reason": "Two cited moments show the before and after.",
        },
        "connects_to_ziv_work": {
            "pass": False,
            "reason": "The build is only mentioned in passing, not shown.",
        },
    }
    cites = [
        {
            "moment_id": str(uuid.uuid4()),
            "source_kind": "fathom_meeting",
            "source_title": "Synthetic weekly call with a sample studio",
            "occurred_at": (week + timedelta(days=1)).isoformat(),
            "span_start_s": 754.0,
            "span_end_s": 812.5,
            "claim_type": "paraphrased",
            "speaker": "Sample Owner",
            "speaker_confidence": "medium",
            "translation_label": "English adaptation from Hebrew",
            "url_private": "https://example.com/private/meeting",
            "excerpt_private": "Synthetic excerpt: we answered within ten minutes and booked two calls.",
        },
        {
            "moment_id": str(uuid.uuid4()),
            "source_kind": "github_commit_group",
            "source_title": "Synthetic inquiry auto-reply change",
            "occurred_at": (week + timedelta(days=2)).isoformat(),
            "claim_type": "demonstrated",
            "code_refs": [
                {
                    "repo": "example/sample-app",
                    "sha": "0a1b2c3d4e5f",
                    "path": "src/inquiry/reply.ts",
                    "url_at_sha": "https://example.com/example/sample-app/blob/0a1b2c3/src/inquiry/reply.ts",
                }
            ],
            "excerpt_private": "Synthetic diff summary: reply template now names the next step.",
        },
    ]
    cands = []
    titles = [
        ("Answer new inquiries in ten minutes, not ten hours", "coaches"),
        ("Why a price list before the first call loses the booking", "event_owners"),
        ("The one-question intake form that replaced a twelve-field form", "both"),
    ]
    for i, (title, audience) in enumerate(titles, 1):
        cands.append(
            TopicCandidate(
                id=uuid.uuid4(),
                workspace_id=WS,
                week_start=week,
                moment_ids=[c["moment_id"] for c in cites],
                title=title,
                lesson="Speed and one clear next step win the first conversation.",
                audience=audience,
                reasons_to_care=[
                    "Most inquiries go cold within an hour",
                    "It costs nothing to fix this week",
                ],
                public_angle="Show the reply habit, never the client or their numbers.",
                public_safety_notes="Client name and exact quote stay private.",
                gates=gates_ok,
                rank=i,
                rank_score=0.9 - i * 0.1,
                citations_private=cites,
                status="selected" if i == 1 else "proposed",
                origin="selector",
                editor_notes="Synthetic note: record this on the Thursday walk."
                if i == 1
                else None,
            )
        )
    packet = RecordingPacket(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cands[0].id,
        version=1,
        bullets=[
            "Most inquiries go cold within an hour",
            "Name the ten minute rule",
            "Tell the rainy walk story",
            "Show the two sentence reply",
            "Close with one action for today",
        ],
        script_phrases=[
            "Most small studios lose leads in the first hour.",
            "Answer every new inquiry within ten minutes.",
            "Do not send a price list before the first call.",
            "Ask one question that moves them to a call.",
        ],
        facebook_post="Synthetic Facebook adaptation.\n\nAnswer fast, then ask one question.",
        linkedin_post="Synthetic LinkedIn adaptation about response time.",
        citations_private=cites,
        public_safety={"checked": True, "status": "clean", "issues": []},
        status="ready",
    )
    rec_dir = WORK / "recordings" / str(WS) / str(cands[0].id)
    rec_dir.mkdir(parents=True, exist_ok=True)
    media_path = rec_dir / "synthetic.mp4"
    media_path.write_bytes(b"synthetic media placeholder")
    (rec_dir / "x.m4a").write_bytes(b"synthetic audio placeholder")
    transcript = [
        {"start_s": 0.0, "end_s": 3.0, "text": "Most small studios lose leads in the first hour."},
        {"start_s": 3.4, "end_s": 4.2, "text": "Answer every new"},
        {"start_s": 6.5, "end_s": 9.0, "text": "Answer every new inquiry within ten minutes."},
        {"start_s": 9.3, "end_s": 12.0, "text": "Do not send a price list before the first call."},
        {"start_s": 12.4, "end_s": 15.0, "text": "Do send a price list before the first call."},
        {"start_s": 18.5, "end_s": 21.0, "text": "Ask one question that moves them to a call."},
    ]
    plan = plan_edit(transcript, packet.script_phrases, duration_s=22.0)
    upload = RecordingUpload(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cands[0].id,
        packet_id=packet.id,
        original_filename="thursday-walk.mp4",
        storage_path=str(media_path),
        sha256="c" * 64,
        duration_s=22.0,
        transcript=transcript,
        edit_plan=plan,
        status="needs_review" if plan["meaning_check"]["status"] == "blocked" else "planned",
        status_detail="Needs review: " + plan["meaning_check"]["issues"][0]["detail"]
        if plan["meaning_check"]["issues"]
        else "Plan ready",
        job_ids=[],
    )
    upload2 = RecordingUpload(
        id=uuid.uuid4(),
        workspace_id=WS,
        candidate_id=cands[1].id,
        original_filename="price-list-walk.m4a",
        storage_path=str(rec_dir / "x.m4a"),
        sha256="d" * 64,
        duration_s=102.0,
        status="transcribing",
        status_detail="Transcribing 1m42s file with local faster-whisper",
        job_ids=[],
    )
    rows = [
        *cands,
        packet,
        upload,
        upload2,
        EditorialFeedback(
            workspace_id=WS,
            candidate_id=cands[0].id,
            kind="approve",
            rating="publish",
            preference_version=1,
            created_by="editor",
        ),
        LLMJob(
            workspace_id=WS,
            job_type="recording_packet",
            agent_name="packet_writer",
            idempotency_key="s1",
            request_json={},
            policy_model="claude-opus-5",
            input_hash="h1",
            status="waiting_capacity",
            attempt_count=2,
            retry_at=now + timedelta(minutes=14),
            error_code="capacity",
        ),
        LLMJob(
            workspace_id=WS,
            job_type="moment_extraction",
            agent_name="moment_extractor",
            idempotency_key="s2",
            request_json={},
            policy_model="claude-opus-5",
            input_hash="h2",
            status="leased",
            attempt_count=1,
            lease_owner="worker-vps-1",
            leased_until=now + timedelta(minutes=8),
        ),
        LLMJob(
            workspace_id=WS,
            job_type="idea_selection",
            agent_name="selector",
            idempotency_key="s3",
            request_json={},
            policy_model="claude-opus-5",
            input_hash="h3",
            status="completed",
            attempt_count=1,
            completed_at=now,
            receipt_json={"auth_method": "claude.ai", "modelUsage": {"claude-opus-5": {}}},
        ),
        EvidenceCollectionRun(
            workspace_id=WS,
            source_kind="fathom_meeting",
            window_start=week,
            window_end=week + timedelta(days=7),
            status="partial",
            counts={"listed": 9, "in_window": 7, "processed": 6, "failed": 1},
            items=[
                {
                    "external_id": "meeting-synthetic-7",
                    "state": "failed",
                    "reason": "transcript not ready",
                }
            ],
            errors=[],
            complete=False,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2),
        ),
        EvidenceCollectionRun(
            workspace_id=WS,
            source_kind="github_commit_group",
            window_start=week,
            window_end=week + timedelta(days=7),
            status="complete",
            counts={"listed": 14, "processed": 5, "unchanged": 9},
            items=[],
            errors=[],
            complete=True,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2),
        ),
        EvidenceCollectionRun(
            workspace_id=WS,
            source_kind="moment_extraction",
            window_start=week,
            window_end=week + timedelta(days=7),
            status="running",
            counts={"sources": 11, "processed": 4},
            items=[],
            errors=[],
            complete=False,
            current_activity="Extracting moments from source 5 of 11 (subscription job)",
            started_at=now - timedelta(minutes=3),
        ),
    ]
    async with session_mod.async_session() as s:
        s.add_all(rows)
        await s.commit()
    return {
        "week": week.date().isoformat(),
        "candidate": str(cands[0].id),
        "candidate2": str(cands[1].id),
    }


def build_app():
    from tce.api.app import create_app
    from tce.db.session import get_db

    app = create_app()
    app.dependency_overrides[get_db] = _smoke_get_db

    async def proxy(scope, receive, send):
        # Simulates the authenticated reverse proxy: the browser never holds the key.
        if scope["type"] == "http" and scope["path"].startswith("/api/v1/"):
            headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"x-tce-editor-key"]
            headers.append((b"x-tce-editor-key", EDITOR_KEY.encode()))
            scope = dict(scope, headers=headers)
        await app(scope, receive, send)

    return proxy


def serve(port: int) -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(build_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return
        time.sleep(0.1)
    raise RuntimeError("server did not start")


CHECK_JS = """
(phone) => {
  const root = document.getElementById('ed-root');
  const vw = window.innerWidth;
  const out = {overflowX: document.documentElement.scrollWidth > vw + 1, wide: [], overlaps: [], small: []};
  if (!root) return out;
  const vis = el => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}); };
  const label = el => (el.tagName + ' ' + (el.id || '') + ' ' + (el.textContent || el.value || '').trim().slice(0, 40));
  for (const el of root.querySelectorAll('*')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 && !el.closest('.ed-table')) out.wide.push(label(el) + ' right=' + Math.round(r.right));
  }
  const inter = [...root.querySelectorAll('button, a, input, select, textarea, summary, label.btn')]
    .filter(el => vis(el) && !(el.type === 'file'));
  for (let i = 0; i < inter.length; i++) {
    const a = inter[i].getBoundingClientRect();
    if (phone && (a.height < 43.5) && !inter[i].closest('.ed-cite a') && inter[i].tagName !== 'A')
      out.small.push(label(inter[i]) + ' h=' + Math.round(a.height));
    for (let j = i + 1; j < inter.length; j++) {
      if (inter[i].contains(inter[j]) || inter[j].contains(inter[i])) continue;
      const b = inter[j].getBoundingClientRect();
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 1 && h > 1) out.overlaps.push(label(inter[i]) + ' X ' + label(inter[j]));
    }
  }
  out.wide = out.wide.slice(0, 20); out.small = out.small.slice(0, 30); out.overlaps = out.overlaps.slice(0, 20);
  return out;
}
"""


def drive(base: str, out: Path, seeded: dict) -> dict:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for name, vp, phone in (
            ("phone", {"width": 390, "height": 844}, True),
            ("desktop", {"width": 1440, "height": 900}, False),
        ):
            ctx = browser.new_context(
                viewport=vp, device_scale_factor=2, is_mobile=phone, has_touch=phone
            )
            page = ctx.new_page()
            errors: list[str] = []

            def on_console(m, errors=errors):
                # The Google Fonts requests are aborted on purpose (offline smoke run).
                if m.type == "error" and "fonts.g" not in (m.location or {}).get("url", ""):
                    errors.append(m.text + " @ " + str((m.location or {}).get("url", "")))

            page.on("console", on_console)
            page.on(
                "requestfailed",
                lambda r, errors=errors: (
                    None if "fonts.g" in r.url else errors.append("request failed: " + r.url)
                ),
            )
            page.on("pageerror", lambda e, errors=errors: errors.append("pageerror: " + str(e)))
            page.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            page.route("**/fonts.gstatic.com/**", lambda r: r.abort())
            page.add_init_script(f"localStorage.setItem('tce_ed_week', '{seeded['week']}')")
            page.goto(base + "/dashboard#editorial", wait_until="domcontentloaded")
            page.wait_for_selector(".ed-card", timeout=20000)
            page.wait_for_selector("#ed-activity .ed-row", timeout=20000)
            page.wait_for_timeout(800)
            steps = {}
            page.screenshot(path=str(out / f"{name}-1-overview.png"), full_page=False)
            steps["overview"] = page.evaluate(CHECK_JS, phone)
            cid = seeded["candidate"]
            page.click(f"#ed-card-{cid} .ed-card-head")
            page.wait_for_selector(f"#ed-pk-{cid} .ed-phrases", timeout=20000)
            page.wait_for_selector(f"#ed-rec-{cid} .ed-table", timeout=20000)
            page.fill(f"#ed-notes-{cid}", "Synthetic smoke note: keep the rainy walk story.")
            page.click(f"#ed-card-{cid} button:has-text('Save notes')")
            page.wait_for_selector(f"#ed-notes-state-{cid}:has-text('Saved')", timeout=10000)
            page.click(f"#ed-card-{cid} button:has-text('Yes, I would publish this')")
            page.wait_for_selector(f"#ed-fb-last-{cid}:has-text('2 feedback items')", timeout=10000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(700)  # the card re-renders once more when its sections reload
            page.locator(f"#ed-card-{cid} .ed-cite details summary").first.click()
            page.locator(
                f"#ed-card-{cid} .ed-sec h4:has-text('Gates')"
            ).scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=str(out / f"{name}-2-card-feedback.png"))
            steps["card"] = page.evaluate(CHECK_JS, phone)
            page.locator(f"#ed-pk-{cid}").scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / f"{name}-3-packet.png"))
            page.click(f"#ed-export-{cid}")
            page.wait_for_selector(f"#ed-pk-{cid} :text('Google not connected')", timeout=15000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(700)  # the packet section re-renders once after export
            page.locator(
                f"#ed-pk-{cid} .ed-row:has-text('Recording doc')"
            ).scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / f"{name}-4-export-result.png"))
            page.locator(f"#ed-rec-{cid}").scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / f"{name}-5-edit-plan.png"))
            steps["plan"] = page.evaluate(CHECK_JS, phone)
            page.locator(f"#ed-pub-{cid}").scroll_into_view_if_needed()
            page.evaluate(
                f"document.querySelectorAll('#ed-pub-{cid} details').forEach(d => d.open = true)"
            )
            page.fill(f"#ed-p-ext-{cid}", "synthetic-post-1")
            page.click(f"#ed-pub-{cid} button:has-text('Record receipt')")
            page.wait_for_selector(f"#ed-pub-{cid} button:has-text('Save outcome')", timeout=10000)
            page.fill(f"#ed-pub-{cid} input[type=number] >> nth=0", "2")
            page.click(f"#ed-pub-{cid} button:has-text('Save outcome')")
            page.wait_for_selector(f"#ed-pub-{cid} :text('Saved')", timeout=10000)
            page.locator(f"#ed-pub-{cid}").scroll_into_view_if_needed()
            page.screenshot(path=str(out / f"{name}-6-receipt.png"))
            steps["receipt"] = page.evaluate(CHECK_JS, phone)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("#ed-activity .ed-row", timeout=20000)
            page.wait_for_timeout(800)
            steps["after_reload_activity"] = page.inner_text("#ed-activity")[:600]
            report[name] = {"console_errors": errors, "checks": steps}
            ctx.close()
        browser.close()
    return report


def drive_links(base: str, out: Path, seeded: dict) -> dict:
    """?week= deep link (valid, non-Monday, invalid), honest 503 text, interrupted upload."""
    from playwright.sync_api import sync_playwright

    result: dict = {}
    llm_503 = json.dumps(
        {
            "detail": "Text generation is not available right now",
            "llm_status": "waiting_capacity",
            "llm_detail": "Synthetic: subscription capacity window closed",
            "job_id": str(uuid.uuid4()),
            "retry_at": None,
        }
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        def page_for(ctx_errors):
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("pageerror", lambda e: ctx_errors.append("pageerror: " + str(e)))
            page.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            page.route("**/fonts.gstatic.com/**", lambda r: r.abort())
            return ctx, page

        errors: list[str] = []
        ctx, page = page_for(errors)
        page.goto(base + f"/?week={seeded['week']}#editorial", wait_until="domcontentloaded")
        page.wait_for_selector(".ed-card", timeout=20000)
        result["valid"] = {
            "url": page.url,
            "input": page.input_value("#ed-week-input"),
            "cards": page.locator(".ed-card").count(),
            "stored": page.evaluate("localStorage.getItem('tce_ed_week')"),
        }
        cid = seeded["candidate2"]
        page.click(f"#ed-card-{cid} .ed-card-head")
        page.wait_for_selector(f"#ed-rec-{cid} .ed-badge:has-text('interrupted')", timeout=20000)
        result["interrupted_upload"] = page.inner_text(f"#ed-rec-{cid}")[:400]
        page.wait_for_selector("#ed-activity .ed-badge:has-text('interrupted')", timeout=20000)
        page.locator(f"#ed-rec-{cid}").scroll_into_view_if_needed()
        page.screenshot(path=str(out / "links-1-interrupted-upload.png"))
        cid1 = seeded["candidate"]
        page.click(f"#ed-card-{cid1} .ed-card-head")
        page.wait_for_selector(
            f"#ed-rec-{cid1} button:has-text('Render uncut with captions')", timeout=20000
        )
        page.locator(f"#ed-rec-{cid1} .ed-details").first.scroll_into_view_if_needed()
        page.screenshot(path=str(out / "links-2-plan-timing-uncut.png"))
        result["plan_panel"] = page.inner_text(f"#ed-rec-{cid1}")[:900]
        ctx.close()

        ctx, page = page_for(errors)
        page.goto(base + "/?week=2026-09-07#editorial", wait_until="domcontentloaded")
        page.wait_for_selector("#ed-candidates .ed-empty, #ed-candidates .ed-card", timeout=20000)
        result["pilot_week"] = {
            "url": page.url,
            "input": page.input_value("#ed-week-input"),
            "header": page.inner_text(".ed-top .ed-sub"),
        }
        ctx.close()

        for label, raw in (
            ("non_monday", "2026-09-09"),
            ("invalid", "2026-02-30"),
            ("junk", "%3Cscript%3E"),
        ):
            ctx, page = page_for(errors)
            page.goto(base + f"/?week={raw}#editorial", wait_until="domcontentloaded")
            page.wait_for_selector("#ed-week-notice", timeout=20000)
            result[label] = {
                "url": page.url,
                "input": page.input_value("#ed-week-input"),
                "notice": page.inner_text("#ed-week-notice"),
                "script_injected": page.evaluate(
                    "document.querySelectorAll('#ed-root script').length"
                ),
            }
            if label == "invalid":
                page.screenshot(path=str(out / "links-3-invalid-week.png"))
            ctx.close()

        ctx, page = page_for(errors)
        page.route(
            "**/api/v1/editorial/candidates?*",
            lambda r: r.fulfill(status=503, content_type="application/json", body=llm_503),
        )
        page.goto(base + f"/?week={seeded['week']}#editorial", wait_until="domcontentloaded")
        page.wait_for_selector("#ed-candidates .ed-err", timeout=20000)
        result["llm_503"] = page.inner_text("#ed-candidates .ed-err")
        page.screenshot(path=str(out / "links-4-subscription-503.png"))
        ctx.close()

        ctx, page = page_for(errors)
        page.route(
            "**/api/v1/editorial/candidates?*",
            lambda r: r.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Private access is not configured"}),
            ),
        )
        page.goto(base + f"/?week={seeded['week']}#editorial", wait_until="domcontentloaded")
        page.wait_for_selector("#ed-candidates .ed-err", timeout=20000)
        result["private_access_503"] = page.inner_text("#ed-candidates .ed-err")
        ctx.close()
        browser.close()
    result["page_errors"] = errors
    checks = [
        result["valid"]["input"] == seeded["week"] and result["valid"]["cards"] > 0,
        "week=" + seeded["week"] in result["valid"]["url"]
        and result["valid"]["url"].endswith("#editorial"),
        result["pilot_week"]["input"] == "2026-09-07" and "Sep 7" in result["pilot_week"]["header"],
        result["non_monday"]["input"] == "2026-09-07"
        and "not a Monday" in result["non_monday"]["notice"],
        "not a valid date" in result["invalid"]["notice"]
        and "2026-02-30" not in result["invalid"]["url"],
        result["junk"]["script_injected"] == 0 and "not a valid date" in result["junk"]["notice"],
        "Private access" not in result["llm_503"]
        and "subscription job waiting capacity" in result["llm_503"],
        "Private access is not configured on the server" in result["private_access_503"],
        "Click Transcribe to retry" in result["interrupted_upload"],
        "Timing: whole seconds" in result["plan_panel"]
        or "Timing: as supplied" in result["plan_panel"],
        not errors,
    ]
    result["failed_checks"] = [i for i, ok in enumerate(checks) if not ok]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WORK / "screens"))
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()
    seeded = asyncio.run(seed())
    serve(args.port)
    import urllib.request

    status = {
        "worker_id": "worker-vps-1",
        "worker_host": "synthetic-host",
        "ok": True,
        "checked_at": datetime.now(UTC).isoformat(),
        "logged_in": True,
        "auth_method": "claude.ai",
        "subscription_type": "max",
        "policy_model": "claude-opus-5",
        "state": "running_job",
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{args.port}/api/v1/llm-jobs/worker-status",
        data=json.dumps(status).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10).read()
    report = drive(f"http://127.0.0.1:{args.port}", Path(args.out), seeded)
    links = drive_links(f"http://127.0.0.1:{args.port}", Path(args.out), seeded)
    print(json.dumps(report, indent=2))
    print(json.dumps({"links": links}, indent=2))
    problems = 0
    for name, r in report.items():
        for step, c in r["checks"].items():
            if isinstance(c, dict):
                problems += (
                    len(c["wide"]) + len(c["overlaps"]) + len(c["small"]) + int(c["overflowX"])
                )
    print(f"screenshots: {args.out}")
    print(f"layout problems: {problems}")
    print(f"link/error checks failed: {links['failed_checks']}")
    return 1 if problems or links["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
