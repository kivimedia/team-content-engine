"""Pipeline execution endpoints - trigger, status, and cancel workflows."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
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

# Track the active generate-week orchestration
_week_generation: dict[str, dict] = {}


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

    # Background task needs its own DB session (request session closes on return)
    async def _run() -> None:
        from tce.db.session import async_session

        async with async_session() as bg_db:
            # Persist run record
            run_record = PipelineRun(
                run_id=run_id,
                workflow=request.workflow,
                status="running",
                day_of_week=request.context.get("day_of_week"),
                started_at=datetime.utcnow(),
            )
            bg_db.add(run_record)
            await bg_db.commit()

            orchestrator = PipelineOrchestrator(
                steps=steps,
                db=bg_db,
                settings=settings,
                run_id=run_id,
            )
            _active_runs[str(run_id)] = orchestrator
            try:
                result = await orchestrator.run(request.context)
                await bg_db.commit()

                # Update run record with results
                run_record = await bg_db.get(PipelineRun, run_record.id)
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
                    await bg_db.commit()

            except Exception as e:
                # Update run record with error
                try:
                    run_record = await bg_db.get(PipelineRun, run_record.id)
                    if run_record:
                        run_record.status = "failed"
                        run_record.completed_at = datetime.utcnow()
                        run_record.error_message = str(e)
                        await bg_db.commit()
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

        async with async_session() as bg_db:
            try:
                # --- Phase 1: Weekly Planner (skipped if approved_plan provided) ---
                if request.skip_planning and request.approved_plan:
                    # Use the pre-approved plan directly
                    status["phase"] = "planning"
                    status["phase_detail"] = "Using approved plan (skipping planning phase)..."
                    status["planner_run_id"] = None

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

                    planner_steps = WORKFLOWS["weekly_planner"]
                    planner_run_id = uuid.uuid4()

                    planner_record = PipelineRun(
                        run_id=planner_run_id,
                        workflow="weekly_planner",
                        status="running",
                        started_at=datetime.utcnow(),
                    )
                    bg_db.add(planner_record)
                    await bg_db.commit()

                    planner_orch = PipelineOrchestrator(
                        steps=planner_steps,
                        db=bg_db,
                        settings=settings,
                        run_id=planner_run_id,
                    )
                    _active_runs[str(planner_run_id)] = planner_orch

                    planner_result = await planner_orch.run(request.context)
                    await bg_db.commit()

                    # Update planner run record
                    planner_record = await bg_db.get(PipelineRun, planner_record.id)
                    if planner_record:
                        has_failures = any(
                            v == "failed" for v in planner_result.get("step_status", {}).values()
                        )
                        planner_record.status = "failed" if has_failures else "completed"
                        planner_record.completed_at = datetime.utcnow()
                        planner_record.step_results = planner_result.get("step_status", {})
                        await bg_db.commit()

                    _active_runs.pop(str(planner_run_id), None)

                    status["planner_run_id"] = str(planner_run_id)

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
                        return

                status["weekly_theme"] = weekly_theme
                status["gift_theme"] = gift_theme
                status["weekly_keyword"] = weekly_keyword

                # --- Phase 2: Daily Content for each day ---
                status["phase"] = "generating_days"
                daily_steps = WORKFLOWS["daily_from_plan"]
                days = weekly_plan.get("days", [])
                day_run_ids: list[str] = []

                for i, day_plan in enumerate(days):
                    day_num = day_plan.get("day_of_week", i)
                    status["phase_detail"] = f"Generating day {i + 1}/5 (day_of_week={day_num})..."
                    status["current_day"] = i

                    day_run_id = uuid.uuid4()
                    day_record = PipelineRun(
                        run_id=day_run_id,
                        workflow="daily_from_plan",
                        status="running",
                        day_of_week=day_num,
                        started_at=datetime.utcnow(),
                    )
                    bg_db.add(day_record)
                    await bg_db.commit()

                    # Build context for this day - inject the pre-planned brief
                    day_context = {
                        **request.context,
                        "day_of_week": day_num,
                        "story_brief": day_plan.get("story_brief", {}),
                        "trend_brief": trend_brief,
                        "weekly_keyword": weekly_keyword,
                        "weekly_theme": weekly_theme,
                        "gift_theme": gift_theme,
                        "guide_title": gift_theme,
                        "connection_to_gift": day_plan.get("connection_to_gift", ""),
                    }

                    day_orch = PipelineOrchestrator(
                        steps=daily_steps,
                        db=bg_db,
                        settings=settings,
                        run_id=day_run_id,
                    )
                    _active_runs[str(day_run_id)] = day_orch

                    day_result = await day_orch.run(day_context)
                    await bg_db.commit()

                    # Update day run record
                    day_record = await bg_db.get(PipelineRun, day_record.id)
                    if day_record:
                        has_failures = any(
                            v == "failed" for v in day_result.get("step_status", {}).values()
                        )
                        day_record.status = "failed" if has_failures else "completed"
                        day_record.completed_at = datetime.utcnow()
                        day_record.step_results = day_result.get("step_status", {})
                        day_record.step_errors = day_result.get("step_errors", {})
                        await bg_db.commit()

                    _active_runs.pop(str(day_run_id), None)
                    day_run_ids.append(str(day_run_id))

                status["day_run_ids"] = day_run_ids

                # --- Phase 3: Build the weekly guide ---
                status["phase"] = "building_guide"
                status["phase_detail"] = "Building weekly guide from all 5 days..."

                guide_steps = WORKFLOWS["guide_only"]
                guide_run_id = uuid.uuid4()

                guide_record = PipelineRun(
                    run_id=guide_run_id,
                    workflow="guide_only",
                    status="running",
                    started_at=datetime.utcnow(),
                )
                bg_db.add(guide_record)
                await bg_db.commit()

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
                    db=bg_db,
                    settings=settings,
                    run_id=guide_run_id,
                )
                _active_runs[str(guide_run_id)] = guide_orch

                guide_result = await guide_orch.run(guide_context)
                await bg_db.commit()

                guide_record = await bg_db.get(PipelineRun, guide_record.id)
                if guide_record:
                    has_failures = any(
                        v == "failed" for v in guide_result.get("step_status", {}).values()
                    )
                    guide_record.status = "failed" if has_failures else "completed"
                    guide_record.completed_at = datetime.utcnow()
                    guide_record.step_results = guide_result.get("step_status", {})
                    await bg_db.commit()

                _active_runs.pop(str(guide_run_id), None)
                status["guide_run_id"] = str(guide_run_id)

                # --- Done ---
                status["phase"] = "completed"
                status["phase_detail"] = "All 5 days + guide generated successfully"
                status["status"] = "completed"

            except Exception as e:
                logger.exception("generate_week.error", week_id=week_id)
                status["phase"] = "failed"
                status["error"] = str(e)
                status["status"] = "failed"

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

    asyncio.create_task(_run_week())

    return {
        "week_id": week_id,
        "status": "started",
        "status_url": f"/api/v1/pipeline/generate-week/{week_id}/status",
    }


@router.get("/generate-week/{week_id}/status")
async def get_week_generation_status(week_id: str) -> dict[str, Any]:
    """Get the status of a generate-week orchestration."""
    if week_id not in _week_generation:
        raise HTTPException(status_code=404, detail="Week generation not found")
    return _week_generation[week_id]
