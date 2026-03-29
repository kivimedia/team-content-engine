"""Pipeline execution endpoints - trigger, status, and cancel workflows."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.pipeline_run import PipelineRun
from tce.orchestrator.engine import PipelineOrchestrator
from tce.orchestrator.workflows import WORKFLOWS
from tce.settings import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# In-memory store for active pipeline runs (DB is the source of truth for completed)
_active_runs: dict[str, PipelineOrchestrator] = {}

# Track the active generate-week orchestration (in-memory cache, DB is source of truth)
_week_generation: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# DB-backed persistence for week generation status
# ---------------------------------------------------------------------------

async def _ensure_week_gen_table(db: AsyncSession) -> None:
    """Create the week_generation_status table if it doesn't exist."""
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS week_generation_status ("
        "  week_id TEXT PRIMARY KEY,"
        "  status_json TEXT NOT NULL,"
        "  updated_at TEXT NOT NULL"
        ")"
    ))
    await db.commit()


async def _persist_week_status(week_id: str, status: dict) -> None:
    """Write current week generation status to DB (fire-and-forget safe)."""
    try:
        from tce.db.session import async_session
        async with async_session() as db:
            await _ensure_week_gen_table(db)
            now = datetime.utcnow().isoformat()
            await db.execute(text(
                "INSERT INTO week_generation_status (week_id, status_json, updated_at) "
                "VALUES (:wid, :sj, :ua) "
                "ON CONFLICT(week_id) DO UPDATE SET status_json = :sj, updated_at = :ua"
            ), {"wid": week_id, "sj": json.dumps(status), "ua": now})
            await db.commit()
    except Exception:
        logger.warning("persist_week_status.failed", week_id=week_id, exc_info=True)


async def _load_week_status(week_id: str, db: AsyncSession) -> dict | None:
    """Load week generation status from DB."""
    try:
        await _ensure_week_gen_table(db)
        row = (await db.execute(
            text("SELECT status_json FROM week_generation_status WHERE week_id = :wid"),
            {"wid": week_id},
        )).first()
        if row:
            return json.loads(row[0])
    except Exception:
        logger.warning("load_week_status.failed", week_id=week_id, exc_info=True)
    return None


async def _load_active_week(db: AsyncSession) -> dict | None:
    """Find any running week generation from DB."""
    try:
        await _ensure_week_gen_table(db)
        row = (await db.execute(
            text("SELECT status_json FROM week_generation_status "
                 "WHERE json_extract(status_json, '$.status') = 'running' "
                 "ORDER BY updated_at DESC LIMIT 1"),
        )).first()
        if row:
            return json.loads(row[0])
    except Exception:
        logger.warning("load_active_week.failed", exc_info=True)
    return None


async def _mark_stale_generations_interrupted() -> None:
    """On startup, mark any 'running' generations as interrupted (server restarted)."""
    try:
        from tce.db.session import async_session
        async with async_session() as db:
            await _ensure_week_gen_table(db)
            rows = (await db.execute(
                text("SELECT week_id, status_json FROM week_generation_status "
                     "WHERE json_extract(status_json, '$.status') = 'running'"),
            )).all()
            for row in rows:
                status = json.loads(row[1])
                status["status"] = "interrupted"
                status["phase"] = "interrupted"
                status["phase_detail"] = "Server restarted during generation"
                await db.execute(text(
                    "UPDATE week_generation_status SET status_json = :sj, updated_at = :ua "
                    "WHERE week_id = :wid"
                ), {"wid": row[0], "sj": json.dumps(status), "ua": datetime.utcnow().isoformat()})
            await db.commit()
            if rows:
                logger.info("marked_stale_generations", count=len(rows))
    except Exception:
        logger.warning("mark_stale_generations.failed", exc_info=True)


class PipelineRunRequest(BaseModel):
    workflow: str = "daily_content"
    context: dict[str, Any] = {}


class PipelineRunResponse(BaseModel):
    run_id: str
    workflow: str
    status: str


class WeekGenerationRequest(BaseModel):
    context: dict[str, Any] = {}
    skip_planning: bool = False
    approved_plan: dict[str, Any] | None = None


@router.post("/run", response_model=PipelineRunResponse)
async def trigger_pipeline(
    request: PipelineRunRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Trigger a pipeline workflow. Returns immediately with a run_id."""
    if request.workflow not in WORKFLOWS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown workflow: {request.workflow}. Available: {list(WORKFLOWS.keys())}",
        )

    steps = WORKFLOWS[request.workflow]
    run_id = uuid.uuid4()

    # Background task - each phase gets its own fresh session to prevent
    # greenlet corruption from failed agent rollbacks.
    async def _run() -> None:
        from tce.db.session import async_session

        # Create run record in its own session
        async with async_session() as init_db:
            run_record = PipelineRun(
                run_id=run_id,
                workflow=request.workflow,
                status="running",
                day_of_week=request.context.get("day_of_week"),
                started_at=datetime.utcnow(),
            )
            init_db.add(run_record)
            await init_db.commit()
            record_id = run_record.id

        # Run pipeline in its own session
        try:
            async with async_session() as pipe_db:
                orchestrator = PipelineOrchestrator(
                    steps=steps,
                    db=pipe_db,
                    settings=settings,
                    run_id=run_id,
                )
                _active_runs[str(run_id)] = orchestrator
                result = await orchestrator.run(request.context)

            # Bookkeeping in a fresh session
            async with async_session() as bk_db:
                run_record = await bk_db.get(PipelineRun, record_id)
                if run_record:
                    has_failures = any(
                        v == "failed" for v in result.get("step_status", {}).values()
                    )
                    run_record.status = "failed" if has_failures else "completed"
                    run_record.completed_at = datetime.utcnow()
                    run_record.step_results = result.get("step_status", {})
                    run_record.step_errors = result.get("step_errors", {})
                    if has_failures:
                        errors = result.get("step_errors", {})
                        run_record.error_message = "; ".join(f"{k}: {v}" for k, v in errors.items())
                    await bk_db.commit()

        except Exception as e:
            try:
                async with async_session() as err_db:
                    run_record = await err_db.get(PipelineRun, record_id)
                    if run_record:
                        run_record.status = "failed"
                        run_record.completed_at = datetime.utcnow()
                        run_record.error_message = str(e)
                        await err_db.commit()
            except Exception:
                pass
        finally:
            _active_runs.pop(str(run_id), None)

    asyncio.create_task(_run())

    return {
        "run_id": str(run_id),
        "workflow": request.workflow,
        "status": "started",
    }


@router.get("/{run_id}/status")
async def get_pipeline_status(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current status of a pipeline run."""
    # Check active runs first (real-time status)
    if run_id in _active_runs:
        return _active_runs[run_id].get_status()

    # Check database for completed/failed runs
    result = await db.execute(select(PipelineRun).where(PipelineRun.run_id == uuid.UUID(run_id)))
    run_record = result.scalar_one_or_none()
    if run_record:
        return {
            "run_id": str(run_record.run_id),
            "status": run_record.status,
            "step_status": run_record.step_results or {},
            "step_errors": run_record.step_errors or {},
            "error_message": run_record.error_message,
            "started_at": run_record.started_at.isoformat() if run_record.started_at else None,
            "completed_at": run_record.completed_at.isoformat()
            if run_record.completed_at
            else None,
        }

    raise HTTPException(status_code=404, detail="Pipeline run not found")


@router.get("/runs")
async def list_pipeline_runs(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List recent pipeline runs."""
    result = await db.execute(
        select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
    )
    runs = result.scalars().all()
    return [
        {
            "run_id": str(r.run_id),
            "workflow": r.workflow,
            "status": r.status,
            "day_of_week": r.day_of_week,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_message": r.error_message,
            "step_results": r.step_results,
        }
        for r in runs
    ]


@router.get("/workflows")
async def list_workflows() -> dict[str, list[str]]:
    """List available workflow definitions."""
    return {name: [step.agent_name for step in steps] for name, steps in WORKFLOWS.items()}


@router.post("/generate-week")
async def generate_week(
    request: WeekGenerationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate a full week of content with unified planning.

    Phase 1: Run weekly_planner (trend scout + strategic 5-day planning)
    Phase 2: Run daily_from_plan for each day (0-4) with pre-assigned story briefs
    Phase 3: Run guide_only to build the weekly guide from all 5 days
    """
    week_id = str(uuid.uuid4())

    async def _run_week() -> None:
        from tce.db.session import async_session

        status = _week_generation[week_id]

        async def _save() -> None:
            """Persist current status to both in-memory cache and DB."""
            await _persist_week_status(week_id, status)

        try:
            # --- Phase 1: Weekly Planner (skipped if approved_plan provided) ---
            if request.skip_planning and request.approved_plan:
                # Use the pre-approved plan directly
                status["phase"] = "planning"
                status["phase_detail"] = "Using approved plan (skipping planning phase)..."
                status["planner_run_id"] = None
                await _save()

                weekly_plan = request.approved_plan
                trend_brief = {}
                weekly_theme = request.approved_plan.get("weekly_theme", "")
                gift_theme = request.approved_plan.get("gift_theme", "")
                weekly_keyword = request.approved_plan.get("cta_keyword", "")

                # Ensure days have story_brief structure
                for day in weekly_plan.get("days", []):
                    if "story_brief" not in day:
                        day["story_brief"] = day

            else:
                status["phase"] = "planning"
                status["phase_detail"] = (
                    "Running weekly planner (trend scout + strategic planning)..."
                )
                await _save()

                planner_steps = WORKFLOWS["weekly_planner"]
                planner_run_id = uuid.uuid4()

                # Each phase gets its own fresh session to avoid greenlet corruption
                # from failed agent steps (rollback poisons the session state).
                async with async_session() as planner_db:
                    planner_record = PipelineRun(
                        run_id=planner_run_id,
                        workflow="weekly_planner",
                        status="running",
                        started_at=datetime.utcnow(),
                    )
                    planner_db.add(planner_record)
                    await planner_db.commit()
                    planner_record_id = planner_record.id

                    planner_orch = PipelineOrchestrator(
                        steps=planner_steps,
                        db=planner_db,
                        settings=settings,
                        run_id=planner_run_id,
                    )
                    _active_runs[str(planner_run_id)] = planner_orch

                    planner_result = await planner_orch.run(request.context)

                # Use a fresh session for bookkeeping after pipeline completes
                async with async_session() as bk_db:
                    planner_record = await bk_db.get(PipelineRun, planner_record_id)
                    if planner_record:
                        has_failures = any(
                            v == "failed" for v in planner_result.get("step_status", {}).values()
                        )
                        planner_record.status = "failed" if has_failures else "completed"
                        planner_record.completed_at = datetime.utcnow()
                        planner_record.step_results = planner_result.get("step_status", {})
                        await bk_db.commit()

                _active_runs.pop(str(planner_run_id), None)

                status["planner_run_id"] = str(planner_run_id)
                await _save()

                # Extract the weekly plan from the orchestrator context
                ctx = planner_result.get("context", {})
                weekly_plan = ctx.get("weekly_plan", {})
                trend_brief = ctx.get("trend_brief", {})
                weekly_theme = ctx.get("weekly_theme", "")
                gift_theme = ctx.get("gift_theme", "")
                weekly_keyword = ctx.get("weekly_keyword", "")

                if not weekly_plan or not weekly_plan.get("days"):
                    status["phase"] = "failed"
                    status["error"] = "Weekly planner did not produce a valid plan"
                    status["status"] = "failed"
                    await _save()
                    return

            status["weekly_theme"] = weekly_theme
            status["gift_theme"] = gift_theme
            status["weekly_keyword"] = weekly_keyword

            # --- Phase 2: Daily Content for each day ---
            status["phase"] = "generating_days"
            daily_steps = WORKFLOWS["daily_from_plan"]
            days = weekly_plan.get("days", [])
            day_run_ids: list[str] = []
            await _save()

            for i, day_plan in enumerate(days):
                day_num = day_plan.get("day_of_week", i)
                status["phase_detail"] = f"Generating day {i + 1}/5 (day_of_week={day_num})..."
                status["current_day"] = i
                await _save()

                day_run_id = uuid.uuid4()

                # Fresh session per day - prevents greenlet corruption from
                # failed agent rollbacks poisoning subsequent days.
                async with async_session() as day_db:
                    day_record = PipelineRun(
                        run_id=day_run_id,
                        workflow="daily_from_plan",
                        status="running",
                        day_of_week=day_num,
                        started_at=datetime.utcnow(),
                    )
                    day_db.add(day_record)
                    await day_db.commit()
                    day_record_id = day_record.id

                    # Build context for this day - inject the pre-planned brief
                    _raw = day_plan.get("story_brief") or day_plan
                    _brief_keys = (
                        "topic", "thesis", "audience", "angle_type", "day_label",
                        "visual_job", "platform_notes", "desired_belief_shift",
                        "evidence_requirements",
                    )
                    story_brief = {
                        k: _raw[k] for k in _brief_keys if k in _raw
                    }
                    day_context = {
                        **request.context,
                        "day_of_week": day_num,
                        "story_brief": story_brief,
                        "trend_brief": trend_brief,
                        "weekly_keyword": weekly_keyword,
                        "weekly_theme": weekly_theme,
                        "gift_theme": gift_theme,
                        "guide_title": gift_theme,
                        "connection_to_gift": day_plan.get("connection_to_gift", ""),
                    }

                    day_orch = PipelineOrchestrator(
                        steps=daily_steps,
                        db=day_db,
                        settings=settings,
                        run_id=day_run_id,
                    )
                    _active_runs[str(day_run_id)] = day_orch

                    day_result = await day_orch.run(day_context)

                # Fresh session for bookkeeping
                async with async_session() as bk_db:
                    day_record = await bk_db.get(PipelineRun, day_record_id)
                    if day_record:
                        has_failures = any(
                            v == "failed" for v in day_result.get("step_status", {}).values()
                        )
                        day_record.status = "failed" if has_failures else "completed"
                        day_record.completed_at = datetime.utcnow()
                        day_record.step_results = day_result.get("step_status", {})
                        day_record.step_errors = day_result.get("step_errors", {})
                        await bk_db.commit()

                _active_runs.pop(str(day_run_id), None)
                day_run_ids.append(str(day_run_id))

            status["day_run_ids"] = day_run_ids
            await _save()

            # --- Phase 3: Build the weekly guide ---
            status["phase"] = "building_guide"
            status["phase_detail"] = "Building weekly guide from all 5 days..."
            await _save()

            guide_steps = WORKFLOWS["guide_only"]
            guide_run_id = uuid.uuid4()

            async with async_session() as guide_db:
                guide_record = PipelineRun(
                    run_id=guide_run_id,
                    workflow="guide_only",
                    status="running",
                    started_at=datetime.utcnow(),
                )
                guide_db.add(guide_record)
                await guide_db.commit()
                guide_record_id = guide_record.id

                # Collect all story briefs for the guide
                all_story_briefs = [d.get("story_brief", {}) for d in days]

                guide_context = {
                    **request.context,
                    "weekly_theme": weekly_theme,
                    "gift_theme": gift_theme,
                    "weekly_keyword": weekly_keyword,
                    "story_briefs": all_story_briefs,
                    "weekly_plan": weekly_plan,
                }

                guide_orch = PipelineOrchestrator(
                    steps=guide_steps,
                    db=guide_db,
                    settings=settings,
                    run_id=guide_run_id,
                )
                _active_runs[str(guide_run_id)] = guide_orch

                guide_result = await guide_orch.run(guide_context)

            async with async_session() as bk_db:
                guide_record = await bk_db.get(PipelineRun, guide_record_id)
                if guide_record:
                    has_failures = any(
                        v == "failed" for v in guide_result.get("step_status", {}).values()
                    )
                    guide_record.status = "failed" if has_failures else "completed"
                    guide_record.completed_at = datetime.utcnow()
                    guide_record.step_results = guide_result.get("step_status", {})
                    await bk_db.commit()

            _active_runs.pop(str(guide_run_id), None)
            status["guide_run_id"] = str(guide_run_id)

            # --- Done ---
            status["phase"] = "completed"
            status["phase_detail"] = "All 5 days + guide generated successfully"
            status["status"] = "completed"
            await _save()

        except Exception as e:
            logger.exception("generate_week.error", week_id=week_id)
            status["phase"] = "failed"
            status["error"] = str(e)
            status["status"] = "failed"
            await _save()

    # Initialize status tracking
    _week_generation[week_id] = {
        "week_id": week_id,
        "status": "running",
        "phase": "starting",
        "phase_detail": "Initializing weekly generation...",
        "current_day": -1,
        "planner_run_id": None,
        "day_run_ids": [],
        "guide_run_id": None,
        "weekly_theme": None,
        "gift_theme": None,
        "weekly_keyword": None,
        "error": None,
    }

    # Persist initial state to DB immediately
    await _persist_week_status(week_id, _week_generation[week_id])

    asyncio.create_task(_run_week())

    return {
        "week_id": week_id,
        "status": "started",
        "status_url": f"/api/v1/pipeline/generate-week/{week_id}/status",
    }


@router.get("/generate-week/active")
async def get_active_generation(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the currently running generation, if any.

    Checks in-memory cache first, falls back to DB for cross-restart recovery.
    """
    # Check in-memory first (fast path for same-process)
    for wid, status in _week_generation.items():
        if status.get("status") == "running":
            return {"active": True, "week_id": wid, **status}

    # Fall back to DB (handles server restart case)
    db_status = await _load_active_week(db)
    if db_status and db_status.get("status") == "running":
        # Server restarted while generation was running - mark as interrupted
        db_status["status"] = "interrupted"
        db_status["phase"] = "interrupted"
        db_status["phase_detail"] = "Server restarted - generation was interrupted"
        wid = db_status.get("week_id", "unknown")
        await _persist_week_status(wid, db_status)
        # Return the interrupted status so frontend can show what happened
        return {"active": True, "week_id": wid, **db_status}

    return {"active": False}


@router.get("/generate-week/{week_id}/status")
async def get_week_generation_status(
    week_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the status of a generate-week orchestration.

    Checks in-memory cache first, falls back to DB for cross-restart recovery.
    """
    if week_id in _week_generation:
        return _week_generation[week_id]

    # Fall back to DB
    db_status = await _load_week_status(week_id, db)
    if db_status:
        # If DB says running but we don't have it in memory, it was interrupted
        if db_status.get("status") == "running":
            db_status["status"] = "interrupted"
            db_status["phase"] = "interrupted"
            db_status["phase_detail"] = "Server restarted - generation was interrupted"
            await _persist_week_status(week_id, db_status)
        return db_status

    raise HTTPException(status_code=404, detail="Week generation not found")


# ---------------------------------------------------------------------------
# "Start From Copy" — polish user-provided copy into a full package
# ---------------------------------------------------------------------------

class PolishCopyRequest(BaseModel):
    copy_text: str
    platform: str = "both"  # "facebook" | "linkedin" | "both"
    cta_keyword: str | None = None
    notes: str | None = None


# DB-backed persistence for polish runs (same pattern as week generation)
async def _ensure_polish_table(db: AsyncSession) -> None:
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS polish_run_status ("
        "  run_id TEXT PRIMARY KEY,"
        "  status_json TEXT NOT NULL,"
        "  updated_at TEXT NOT NULL"
        ")"
    ))
    await db.commit()


async def _persist_polish_status(run_id: str, status: dict) -> None:
    try:
        from tce.db.session import async_session
        async with async_session() as db:
            await _ensure_polish_table(db)
            now = datetime.utcnow().isoformat()
            await db.execute(text(
                "INSERT INTO polish_run_status (run_id, status_json, updated_at) "
                "VALUES (:rid, :sj, :ua) "
                "ON CONFLICT(run_id) DO UPDATE SET status_json = :sj, updated_at = :ua"
            ), {"rid": run_id, "sj": json.dumps(status), "ua": now})
            await db.commit()
    except Exception:
        logger.warning("persist_polish_status.failed", run_id=run_id, exc_info=True)


async def _load_polish_status(run_id: str, db: AsyncSession) -> dict | None:
    try:
        await _ensure_polish_table(db)
        row = (await db.execute(
            text("SELECT status_json FROM polish_run_status WHERE run_id = :rid"),
            {"rid": run_id},
        )).first()
        if row:
            return json.loads(row[0])
    except Exception:
        logger.warning("load_polish_status.failed", run_id=run_id, exc_info=True)
    return None


_polish_runs: dict[str, dict] = {}


@router.post("/polish-copy")
async def polish_copy(
    request: PolishCopyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Polish user-provided copy into a full content package.

    Runs: copy_analyzer -> cta_agent -> copy_polisher -> creative_director -> qa_agent
    Returns immediately with a run_id for polling.
    """
    run_id = str(uuid.uuid4())

    async def _run_polish() -> None:
        from tce.db.session import async_session

        status = _polish_runs[run_id]

        async def _save() -> None:
            await _persist_polish_status(run_id, status)

        try:
            status["phase"] = "running"
            status["phase_detail"] = "Starting copy polish pipeline..."
            await _save()

            pipeline_run_id = uuid.uuid4()

            async with async_session() as pipe_db:
                run_record = PipelineRun(
                    run_id=pipeline_run_id,
                    workflow="polish_from_copy",
                    status="running",
                    started_at=datetime.utcnow(),
                )
                pipe_db.add(run_record)
                await pipe_db.commit()
                record_id = run_record.id

                steps = WORKFLOWS["polish_from_copy"]
                orchestrator = PipelineOrchestrator(
                    steps=steps,
                    db=pipe_db,
                    settings=settings,
                    run_id=pipeline_run_id,
                )
                _active_runs[str(pipeline_run_id)] = orchestrator
                status["pipeline_run_id"] = str(pipeline_run_id)
                await _save()

                context = {
                    "raw_copy": request.copy_text,
                    "platform": request.platform,
                    "cta_keyword": request.cta_keyword or "",
                    "notes": request.notes or "",
                }

                result = await orchestrator.run(context)

            # Bookkeeping
            async with async_session() as bk_db:
                run_record = await bk_db.get(PipelineRun, record_id)
                if run_record:
                    has_failures = any(
                        v == "failed" for v in result.get("step_status", {}).values()
                    )
                    run_record.status = "failed" if has_failures else "completed"
                    run_record.completed_at = datetime.utcnow()
                    run_record.step_results = result.get("step_status", {})
                    run_record.step_errors = result.get("step_errors", {})
                    if has_failures:
                        errors = result.get("step_errors", {})
                        run_record.error_message = "; ".join(f"{k}: {v}" for k, v in errors.items())
                    await bk_db.commit()

            _active_runs.pop(str(pipeline_run_id), None)

            status["phase"] = "completed"
            status["phase_detail"] = "Copy polished and packaged successfully"
            status["status"] = "completed"
            status["pipeline_run_id"] = str(pipeline_run_id)
            status["step_status"] = result.get("step_status", {})
            await _save()

        except Exception as e:
            logger.exception("polish_copy.error", run_id=run_id)
            status["phase"] = "failed"
            status["error"] = str(e)
            status["status"] = "failed"
            await _save()

    _polish_runs[run_id] = {
        "run_id": run_id,
        "status": "running",
        "phase": "starting",
        "phase_detail": "Initializing copy polish...",
        "pipeline_run_id": None,
        "step_status": {},
        "error": None,
    }

    await _persist_polish_status(run_id, _polish_runs[run_id])
    asyncio.create_task(_run_polish())

    return {
        "run_id": run_id,
        "status": "started",
        "status_url": f"/api/v1/pipeline/polish-copy/{run_id}/status",
    }


@router.get("/polish-copy/{run_id}/status")
async def get_polish_status(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get status of a polish-copy run."""
    if run_id in _polish_runs:
        status = _polish_runs[run_id]
        # Enrich with live step_status from orchestrator if running
        pipe_id = status.get("pipeline_run_id")
        if pipe_id and pipe_id in _active_runs:
            live = _active_runs[pipe_id].get_status()
            status["step_status"] = live.get("step_status", status.get("step_status", {}))
            # Update phase_detail with current running step
            for sname, sval in live.get("step_status", {}).items():
                if sval == "running":
                    status["phase_detail"] = f"Running {sname}..."
                    break
        return status

    db_status = await _load_polish_status(run_id, db)
    if db_status:
        if db_status.get("status") == "running":
            db_status["status"] = "interrupted"
            db_status["phase"] = "interrupted"
            db_status["phase_detail"] = "Server restarted - polish was interrupted"
            await _persist_polish_status(run_id, db_status)
        return db_status

    raise HTTPException(status_code=404, detail="Polish run not found")


@router.get("/polish-copy/active")
async def get_active_polish(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the currently running polish-copy run, if any."""
    for rid, status in _polish_runs.items():
        if status.get("status") == "running":
            return {"active": True, "run_id": rid, **status}
    return {"active": False}


# ---------------------------------------------------------------------------
# Brainstorm — conversational chat about a specific package
# ---------------------------------------------------------------------------

class BrainstormRequest(BaseModel):
    message: str
    package_id: str | None = None
    history: list[dict[str, str]] = []


@router.post("/brainstorm")
async def brainstorm(
    request: BrainstormRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Conversational brainstorm about a content package.

    If package_id is provided, loads the package and injects it as context.
    Uses Haiku for fast, cheap responses. Stateless - frontend maintains history.
    """
    from tce.models.post_package import PostPackage

    system_parts = [
        "You are a creative content strategist for Team Content Engine. "
        "You help brainstorm ideas, refine copy, suggest angles, and improve content packages. "
        "Be concise, creative, and actionable. No fluff."
    ]

    if request.package_id:
        try:
            pkg = await db.get(PostPackage, request.package_id)
            if pkg:
                pkg_context = []
                if pkg.facebook_post:
                    pkg_context.append(f"Facebook post:\n{pkg.facebook_post}")
                if pkg.linkedin_post:
                    pkg_context.append(f"LinkedIn post:\n{pkg.linkedin_post}")
                if pkg.hook_variants:
                    pkg_context.append(f"Hook variants: {', '.join(pkg.hook_variants[:5])}")
                if pkg.cta_keyword:
                    pkg_context.append(f"CTA keyword: {pkg.cta_keyword}")
                if pkg.image_prompts:
                    prompts = pkg.image_prompts if isinstance(pkg.image_prompts, list) else []
                    names = [p.get("prompt_name", "unnamed") for p in prompts[:3]]
                    pkg_context.append(f"Image concepts: {', '.join(names)}")

                system_parts.append(
                    "\n\nYou are discussing this content package:\n" + "\n\n".join(pkg_context)
                )
        except Exception:
            logger.warning("brainstorm.package_load_failed", package_id=request.package_id)

    system_prompt = "\n".join(system_parts)

    # Build messages from history
    messages = []
    for msg in request.history[-20:]:  # Cap at 20 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": request.message})

    # Use Haiku for fast, cheap conversational responses
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    response = await client.messages.create(
        model=settings.haiku_model,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )

    reply = response.content[0].text if response.content else "I couldn't generate a response."

    return {
        "reply": reply,
        "model": settings.haiku_model,
    }
