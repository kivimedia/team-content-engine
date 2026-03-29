"""Start the TCE dashboard with a local SQLite DB and pre-loaded guide.

Usage: python scripts/serve_with_guide.py
Then open: http://localhost:8000/dashboard

This bypasses PostgreSQL by using a local SQLite file and loading
the most recently generated guide JSON into the DB on startup.
"""

import asyncio
import json
import os
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta
from glob import glob
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Override database URL BEFORE any tce imports
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tce_local.db")
DB_URL = f"sqlite+aiosqlite:///{DB_PATH}"
os.environ["TCE_DATABASE_URL"] = DB_URL

# Register SQLite adapters for Python types that PostgreSQL handles natively.
# ARRAY and JSONB columns store list/dict values - SQLite needs them as JSON strings.
# UUID columns (PG_UUID compiled to TEXT) need string conversion.
sqlite3.register_adapter(list, lambda v: json.dumps(v))
sqlite3.register_adapter(dict, lambda v: json.dumps(v))
sqlite3.register_adapter(uuid.UUID, lambda v: str(v))

import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Register SQLite compilers for PostgreSQL-specific column types.
# This lets Base.metadata.create_all() work on SQLite with models that use JSONB/ARRAY/PG_UUID.
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(ARRAY, "sqlite")
def _array_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(PG_UUID, "sqlite")
def _pguuid_sqlite(type_, compiler, **kw):
    return "TEXT"

# Patch the session module before app imports it
import tce.db.session as session_mod

engine = create_async_engine(DB_URL, echo=False)
async_session_local = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Monkey-patch the session module
session_mod.engine = engine
session_mod.async_session = async_session_local


async def _get_db_override():
    async with async_session_local() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def find_latest_guide_json():
    """Find the most recent guide JSON in the project root."""
    project_root = os.path.join(os.path.dirname(__file__), "..")
    json_files = glob(os.path.join(project_root, "*.json"))
    # Filter to guide-like files (have guide_title key)
    guide_files = []
    for f in json_files:
        try:
            with open(f) as fh:
                data = json.load(fh)
                if "guide_title" in data and "sections" in data:
                    guide_files.append((f, data))
        except Exception:
            continue
    if not guide_files:
        return None, None
    # Return the most recently modified
    guide_files.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
    return guide_files[0]


def build_markdown(guide: dict) -> str:
    """Build markdown preview from guide sections (same logic as pipeline_saver)."""
    parts = [f"# {guide.get('guide_title', 'Weekly Guide')}\n"]
    if guide.get("subtitle"):
        parts.append(f"*{guide['subtitle']}*\n")

    for sec in guide.get("sections", []):
        sec_type = sec.get("type", "narrative")
        if sec_type == "narrative":
            parts.append(f"\n## {sec.get('title', '')}\n")
            parts.append(sec.get("content", ""))
        elif sec_type == "callout":
            parts.append(f"\n> **{sec.get('label', 'NOTE')}:** {sec.get('content', '')}\n")
        elif sec_type == "quick_win":
            parts.append(f"\n## {sec.get('title', 'Quick Win')}\n")
            parts.append(sec.get("instruction", ""))
            headers = sec.get("table_headers", [])
            if headers:
                parts.append("\n| " + " | ".join(headers) + " |")
                parts.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for _ in range(sec.get("table_rows", 5)):
                    parts.append("| " + " | ".join([""] * len(headers)) + " |")
            if sec.get("what_you_learn"):
                parts.append(f"\n> **What you'll learn:** {sec['what_you_learn']}\n")
        elif sec_type == "comparison":
            parts.append(f"\n## {sec.get('title', '')}\n")
            bad = sec.get("bad_items", [])
            good = sec.get("good_items", [])
            parts.append(f"| {sec.get('bad_label', 'Before')} | {sec.get('good_label', 'After')} |")
            parts.append("| --- | --- |")
            for i in range(max(len(bad), len(good))):
                b = bad[i] if i < len(bad) else ""
                g = good[i] if i < len(good) else ""
                parts.append(f"| {b} | {g} |")
        elif sec_type == "framework":
            parts.append(f"\n## {sec.get('title', '')}\n")
            if sec.get("intro"):
                parts.append(sec["intro"])
            for i, step in enumerate(sec.get("steps", []), 1):
                parts.append(f"\n### {i}. {step.get('label', '')}\n")
                parts.append(step.get("explanation", ""))
                for b in step.get("bullets", []):
                    parts.append(f"- {b}")
                if step.get("action"):
                    parts.append(f"\n**ACTION:** {step['action']}")
                if step.get("deliverable"):
                    parts.append(f"\n*{step['deliverable']}*")
        elif sec_type == "scenarios":
            parts.append(f"\n## {sec.get('title', '')}\n")
            for s in sec.get("scenarios", []):
                parts.append(f"\n**{s.get('situation', '')}**")
                parts.append(s.get("response", ""))
        elif sec_type == "closing":
            parts.append(f"\n---\n\n**{sec.get('headline', '')}**\n")
            for item in sec.get("you_now_have", []):
                parts.append(f"- {item}")
            if sec.get("cta"):
                parts.append(f"\n*{sec['cta']}*")

    return "\n".join(parts)


async def setup_db_and_load_guide():
    """Create tables if DB is new, seed initial data only on first run.

    IMPORTANT: The DB is persistent across restarts. We only seed when
    the DB file doesn't exist yet. This preserves generated packages,
    pipeline runs, and all user data between restarts.
    """
    db_exists = os.path.exists(DB_PATH)

    # Import all models so Base.metadata knows every table
    import tce.models  # noqa: F401 - triggers model registration
    from tce.models.pipeline_run import PipelineRun  # noqa: F401 - not in __init__
    from tce.models.weekly_plan import WeeklyPlan  # noqa: F401 - not in __init__
    from tce.db.base import Base

    # Create all tables from ORM metadata (safe to re-run - uses IF NOT EXISTS)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if db_exists:
        # DB already has data - check if it has content
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM content_calendar"))
            count = result.scalar()
        if count > 0:
            print(f"DB exists with {count} calendar entries - skipping seed (data is persistent)")
            return
        print("DB exists but calendar is empty - seeding initial data")

    json_path, guide_data = find_latest_guide_json()
    if not guide_data:
        print("WARNING: No guide JSON found in project root. Dashboard will show empty guides.")
        return

    # Find corresponding DOCX
    docx_name = Path(json_path).stem + ".docx"
    docx_path = os.path.join(os.path.dirname(json_path), docx_name)
    if not os.path.exists(docx_path):
        docx_path = None
    else:
        docx_path = str(Path(docx_path).resolve())

    markdown_content = build_markdown(guide_data)
    guide_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO weekly_guides "
                "(id, created_at, updated_at, week_start_date, weekly_theme, guide_title, "
                "docx_path, markdown_content, cta_keyword, downloads_count, is_archived) "
                "VALUES (:id, :now, :now, :wsd, :wt, :gt, :dp, :mc, :ck, 0, 0)"
            ),
            {
                "id": guide_id,
                "now": now,
                "wsd": date.today().isoformat(),
                "wt": guide_data.get("weekly_theme", "AI agents replacing SaaS dashboards"),
                "gt": guide_data.get("guide_title", "Weekly Guide"),
                "dp": docx_path,
                "mc": markdown_content,
                "ck": guide_data.get("cta_keyword", "GUIDE"),
            },
        )

    print(f"Loaded guide: {guide_data.get('guide_title')}")
    print(f"  Guide ID: {guide_id}")
    print(f"  JSON source: {json_path}")
    print(f"  DOCX path: {docx_path or 'NOT FOUND'}")
    print(f"  Markdown preview: {len(markdown_content)} chars")

    # The weekly plan generated by weekly_planner in a previous session.
    # This is the plan Ziv paid for and worked with - reconstructed from
    # regenerate_guide.py SAMPLE_CONTEXT and the guide content.
    WEEKLY_PLAN = {
        "weekly_theme": "AI agents are replacing SaaS dashboards - and most businesses aren't ready",
        "cta_keyword": "AGENTSHIFT",
        "gift_theme": {
            "title": "The Agent Revolution: Why Your SaaS Stack Is About to Become Obsolete",
            "subtitle": "How smart businesses are replacing dashboard-heavy tools with AI agents that actually do the work",
        },
        "days": [
            {
                "day_of_week": 0,
                "day_label": "Monday",
                "angle_type": "big_shift_explainer",
                "topic": "Why AI agents will replace 40% of SaaS tools by 2027",
                "thesis": (
                    "The next wave of AI isn't chatbots - it's autonomous agents that do the "
                    "work dashboards only show you. Businesses still buying dashboard-first "
                    "SaaS are investing in rearview mirrors."
                ),
                "audience": "Agency owners and ops leaders doing $10K-100K/mo who are drowning in SaaS tools",
                "desired_belief_shift": (
                    "FROM: 'I need better dashboards and more integrations' "
                    "TO: 'I need fewer tools that actually do the work for me'"
                ),
                "visual_job": "cinematic_symbolic",
                "connection_to_gift": "Monday sets the strategic context for why SaaS stacks are failing - the guide digs deeper with data",
            },
            {
                "day_of_week": 1,
                "day_label": "Tuesday",
                "angle_type": "tactical_workflow_guide",
                "topic": "Your 15-minute SaaS stack audit - find the $50K you're wasting",
                "thesis": (
                    "The average company uses 137 SaaS tools but 68% of that spend is wasted. "
                    "Here's a 15-minute audit to find which tools an AI agent could replace tomorrow."
                ),
                "audience": "Ops managers and agency owners paying for 20+ SaaS subscriptions",
                "desired_belief_shift": (
                    "FROM: 'We need all these tools' "
                    "TO: 'Half of these could be replaced by one agent workflow'"
                ),
                "visual_job": "proof_diagram",
                "connection_to_gift": "Tuesday's audit is the practical Quick Win from the guide - the step-by-step table",
            },
            {
                "day_of_week": 2,
                "day_label": "Wednesday",
                "angle_type": "contrarian_diagnosis",
                "topic": "Dashboard thinking is killing your productivity - here's the mental model shift",
                "thesis": (
                    "We've been trained to think in dashboards: monitor, analyze, decide, act. "
                    "Agent thinking flips it: define outcome, delegate, verify. Most teams are "
                    "stuck in dashboard mode without realizing it."
                ),
                "audience": "Team leads and founders who feel overwhelmed by their own tools",
                "desired_belief_shift": (
                    "FROM: 'I need to check my dashboards more often' "
                    "TO: 'I need tools that act on my behalf while I sleep'"
                ),
                "visual_job": "emotional_alternate",
                "connection_to_gift": "Wednesday challenges the assumption behind the guide's comparison table - Dashboard vs Agent thinking",
            },
            {
                "day_of_week": 3,
                "day_label": "Thursday",
                "angle_type": "case_study_build_story",
                "topic": "Salesforce Agentforce hit 1 billion actions in 90 days - here's what that means for your agency",
                "thesis": (
                    "Salesforce didn't just launch another feature - Agentforce processed over "
                    "1 billion autonomous agent actions in its first quarter. When the biggest "
                    "SaaS company on earth goes all-in on agents, the rest of us should pay attention."
                ),
                "audience": "Agency owners using Salesforce, HubSpot, or similar CRM/automation stacks",
                "desired_belief_shift": (
                    "FROM: 'AI agents are a nice-to-have experiment' "
                    "TO: 'The enterprise already moved - I need to catch up'"
                ),
                "visual_job": "cinematic_symbolic",
                "connection_to_gift": "Thursday proves the AGENT framework from the guide with Salesforce's real-world results",
            },
            {
                "day_of_week": 4,
                "day_label": "Friday",
                "angle_type": "second_order_implication",
                "topic": "The AGENT framework: 5 steps from dashboard dependency to autonomous operations",
                "thesis": (
                    "McKinsey says AI agents could automate 60-70% of current work activities. "
                    "But most businesses will fumble the transition because they're thinking about "
                    "AI as a tool, not as a teammate. The AGENT framework shows you the path."
                ),
                "audience": "Strategic thinkers and founders planning their 2026-2027 tech stack",
                "desired_belief_shift": (
                    "FROM: 'AI will help me do my work faster' "
                    "TO: 'AI agents will do entire categories of work for me'"
                ),
                "visual_job": "proof_diagram",
                "connection_to_gift": "Friday zooms out to the full framework - the guide's centerpiece that ties the whole week together",
            },
        ],
    }

    # Seed a pipeline_run record so the dashboard can show it was generated
    run_id = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO pipeline_runs "
                "(id, created_at, updated_at, run_id, workflow, status, started_at, "
                "completed_at, step_results, context_snapshot, total_cost_usd) "
                "VALUES (:id, :now, :now, :run_id, 'weekly_planner', 'completed', :now, "
                ":now, :step_results, :ctx_snapshot, :cost)"
            ),
            {
                "id": run_id,
                "run_id": run_id,
                "now": now,
                "step_results": json.dumps({"weekly_planner": {"weekly_plan": WEEKLY_PLAN}}),
                "ctx_snapshot": json.dumps({"weekly_theme": WEEKLY_PLAN["weekly_theme"]}),
                "cost": 0.12,
            },
        )

    # Seed story_briefs for each day
    async with engine.begin() as conn:
        for day in WEEKLY_PLAN["days"]:
            brief_id = str(uuid.uuid4())
            await conn.execute(
                text(
                    "INSERT INTO story_briefs "
                    "(id, created_at, updated_at, topic, thesis, audience, angle_type, "
                    "desired_belief_shift, evidence_requirements, cta_goal, visual_job) "
                    "VALUES (:id, :now, :now, :topic, :thesis, :aud, :angle, :shift, "
                    ":evidence, :cta, :vis)"
                ),
                {
                    "id": brief_id,
                    "now": now,
                    "topic": day["topic"],
                    "thesis": day["thesis"],
                    "aud": day["audience"],
                    "angle": day["angle_type"],
                    "shift": day["desired_belief_shift"],
                    "evidence": json.dumps(day.get("evidence_requirements", [])),
                    "cta": WEEKLY_PLAN["cta_keyword"],
                    "vis": day["visual_job"],
                },
            )

    # Seed content_calendar for current week (Mon-Fri) with actual plan topics
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    async with engine.begin() as conn:
        for day in WEEKLY_PLAN["days"]:
            dow = day["day_of_week"]
            d = monday + timedelta(days=dow)
            entry_id = str(uuid.uuid4())
            status = "planned"
            plan_ctx = json.dumps({
                "thesis": day["thesis"],
                "audience": day["audience"],
                "belief_shift": day["desired_belief_shift"],
                "visual_job": day["visual_job"],
                "connection_to_gift": day["connection_to_gift"],
                "_weekly": {
                    "weekly_theme": WEEKLY_PLAN["weekly_theme"],
                    "gift_theme": WEEKLY_PLAN["gift_theme"],
                    "gift_sections": [
                        "The $50,000 Dashboard Problem",
                        "Your 15-Minute SaaS Stack Audit",
                        "Dashboard Thinking vs. Agent Thinking",
                        "The AGENT Framework: From Dashboard Dependency to Autonomous Operations",
                        "What To Do When...",
                        "Closing",
                    ],
                    "cta_keyword": WEEKLY_PLAN["cta_keyword"],
                },
            })
            await conn.execute(
                text(
                    "INSERT INTO content_calendar "
                    "(id, created_at, updated_at, date, day_of_week, angle_type, topic, "
                    "post_package_id, plan_context, status, is_buffer, buffer_priority, "
                    "weekly_guide_id, weekly_plan_id, operator_notes) "
                    "VALUES (:id, :now, :now, :d, :dow, :at, :topic, NULL, :plan_ctx, "
                    ":status, 0, 0, :guide_id, NULL, NULL)"
                ),
                {
                    "id": entry_id,
                    "now": now,
                    "d": d.isoformat(),
                    "dow": dow,
                    "at": day["angle_type"],
                    "topic": day["topic"],
                    "plan_ctx": plan_ctx,
                    "status": status,
                    "guide_id": guide_id,
                },
            )
    print(f"  Seeded calendar: {monday.isoformat()} to {(monday + timedelta(days=4)).isoformat()}")
    print(f"  Plan theme: {WEEKLY_PLAN['weekly_theme']}")
    print(f"  CTA keyword: {WEEKLY_PLAN['cta_keyword']}")
    for day in WEEKLY_PLAN["days"]:
        print(f"    {day['day_label']}: {day['topic'][:60]}...")


def main():
    # Run setup first (before importing app which triggers module-level DB usage)
    asyncio.run(setup_db_and_load_guide())

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    from tce.api.app import app
    from tce.db.session import get_db

    app.dependency_overrides[get_db] = _get_db_override

    # Remove routes that use UUID types or ORM models incompatible with SQLite
    routes_to_remove = [
        "/api/v1/content/guides/{guide_id}/download",
        "/api/v1/content/guides/{guide_id}",
        "/api/v1/content/guides/{guide_id}/archive",
        "/api/v1/content/guides/{guide_id}/unarchive",
        "/api/v1/calendar/",
        "/api/v1/calendar/today",
    ]
    app.routes[:] = [
        r for r in app.routes
        if not (hasattr(r, "path") and r.path in routes_to_remove)
    ]

    def _parse_calendar_row(row_dict):
        """Parse JSON string fields in calendar rows so the frontend gets objects."""
        d = dict(row_dict)
        if isinstance(d.get("plan_context"), str):
            try:
                d["plan_context"] = json.loads(d["plan_context"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d

    # Calendar routes (SQLite-compatible)
    @app.get("/api/v1/calendar/")
    async def list_calendar_sqlite(start: str = None, end: str = None):
        async with async_session_local() as session:
            sql = "SELECT * FROM content_calendar"
            params = {}
            clauses = []
            if start:
                clauses.append("date >= :start")
                params["start"] = start
            if end:
                clauses.append("date <= :end")
                params["end"] = end
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY date"
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
            return [_parse_calendar_row(r._mapping) for r in rows]

    @app.get("/api/v1/calendar/today")
    async def get_today_sqlite():
        today_str = date.today().isoformat()
        async with async_session_local() as session:
            result = await session.execute(
                text("SELECT * FROM content_calendar WHERE date = :d"),
                {"d": today_str},
            )
            row = result.first()
            if row:
                return _parse_calendar_row(row._mapping)
            return None

    @app.get("/api/v1/content/guides/{guide_id}/download")
    async def download_guide_sqlite(guide_id: str):
        async with async_session_local() as session:
            result = await session.execute(
                text("SELECT docx_path, guide_title FROM weekly_guides WHERE id = :gid"),
                {"gid": guide_id},
            )
            row = result.first()
            if not row:
                raise HTTPException(status_code=404, detail="Guide not found")
            docx_path_val, guide_title = row
            if not docx_path_val:
                raise HTTPException(status_code=404, detail="No DOCX file")
            p = Path(docx_path_val)
            if not p.exists():
                raise HTTPException(status_code=404, detail=f"DOCX not on disk: {docx_path_val}")
            return FileResponse(
                path=str(p),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=f"{guide_title}.docx",
            )

    @app.get("/api/v1/content/guides/{guide_id}")
    async def get_guide_sqlite(guide_id: str):
        async with async_session_local() as session:
            result = await session.execute(
                text("SELECT * FROM weekly_guides WHERE id = :gid"),
                {"gid": guide_id},
            )
            row = result.first()
            if not row:
                raise HTTPException(status_code=404, detail="Guide not found")
            return dict(row._mapping)

    @app.post("/api/v1/content/guides/{guide_id}/archive")
    async def archive_guide_sqlite(guide_id: str):
        async with async_session_local() as session:
            await session.execute(
                text("UPDATE weekly_guides SET is_archived = 1 WHERE id = :gid"),
                {"gid": guide_id},
            )
            await session.commit()
            return {"status": "archived"}

    @app.post("/api/v1/content/guides/{guide_id}/unarchive")
    async def unarchive_guide_sqlite(guide_id: str):
        async with async_session_local() as session:
            await session.execute(
                text("UPDATE weekly_guides SET is_archived = 0 WHERE id = :gid"),
                {"gid": guide_id},
            )
            await session.commit()
            return {"status": "unarchived"}

    # Mark any stale "running" week generations as interrupted (server restart)
    from tce.api.routers.pipeline import _mark_stale_generations_interrupted
    asyncio.run(_mark_stale_generations_interrupted())

    print("\nStarting TCE Dashboard...")
    print("Open: http://localhost:8000/dashboard")
    print("Guide visible in Packages tab")
    print("Press Ctrl+C to stop\n")

    port = int(os.environ.get("TCE_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
