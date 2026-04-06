"""Pipeline execution endpoints - trigger, status, and cancel workflows."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import async_session, get_db
from tce.models.pattern_template import PatternTemplate
from tce.models.pipeline_run import PipelineRun
from tce.models.video_lead_script import VideoLeadScript
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
    resume_from_step: str | None = None


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
                result = await orchestrator.run(
                    request.context,
                    resume_from_step=request.resume_from_step,
                )

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
                    # Persist key outputs from pipeline context for result retrieval
                    ctx = result.get("context", {})
                    if ctx:
                        snapshot_keys = [
                            "video_lead_script", "story_brief", "narration_script",
                        ]
                        snapshot = {k: ctx[k] for k in snapshot_keys if k in ctx}
                        if snapshot:
                            run_record.context_snapshot = snapshot
                        # Save VideoLeadScript to dedicated table
                        vls = ctx.get("video_lead_script")
                        if vls and isinstance(vls, dict):
                            story = ctx.get("story_brief", {})
                            script_record = VideoLeadScript(
                                title=vls.get("title", "Untitled"),
                                title_pattern=vls.get("title_pattern"),
                                hook=vls.get("hook"),
                                full_script=vls.get("full_script"),
                                sections=vls.get("sections"),
                                word_count=vls.get("word_count"),
                                estimated_duration_minutes=vls.get("estimated_duration_minutes"),
                                target_audience=vls.get("target_audience"),
                                key_takeaway=vls.get("key_takeaway"),
                                niche=ctx.get("niche", "coaching"),
                                seo_description=vls.get("seo_description"),
                                tags=vls.get("tags"),
                                blog_repurpose_outline=vls.get("blog_repurpose_outline"),
                                pipeline_run_id=run_id,
                                topic=story.get("topic"),
                                thesis=story.get("thesis"),
                            )
                            bk_db.add(script_record)
                            logger.info("pipeline.video_lead_script_saved", id=str(script_record.id))
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
            "step_logs": {},
            "error_message": run_record.error_message,
            "result": run_record.context_snapshot or {},
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
                        day["story_brief"] = {k: v for k, v in day.items()}

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

            # --- Create calendar entries for this week ---
            # The orchestrator links packages to calendar entries by day_of_week,
            # so we must ensure entries exist before generating daily content.
            from tce.models.content_calendar import ContentCalendarEntry

            DEFAULT_CADENCE = {
                0: "big_shift_explainer",
                1: "tactical_workflow_guide",
                2: "contrarian_diagnosis",
                3: "case_study_build_story",
                4: "second_order_implication",
            }

            today = date.today()
            week_start = today - timedelta(days=today.weekday())  # Monday
            days_list = weekly_plan.get("days", [])

            async with async_session() as cal_db:
                for i, day_plan in enumerate(days_list):
                    day_num = day_plan.get("day_of_week", i)
                    entry_date = week_start + timedelta(days=day_num)
                    # Extract story fields without circular refs
                    story = day_plan.get("story_brief") or day_plan
                    # Build a flat dict - exclude story_brief to avoid circular reference
                    story_flat = {k: v for k, v in story.items() if k != "story_brief"}

                    result = await cal_db.execute(
                        select(ContentCalendarEntry).where(
                            ContentCalendarEntry.date == entry_date
                        )
                    )
                    entry = result.scalar_one_or_none()

                    enriched_context = {
                        **story_flat,
                        "_weekly": {
                            "weekly_theme": weekly_theme,
                            "gift_theme": gift_theme,
                            "cta_keyword": weekly_keyword,
                        },
                    }

                    if entry:
                        entry.topic = story.get("topic", entry.topic)
                        entry.angle_type = story.get(
                            "angle_type",
                            DEFAULT_CADENCE.get(day_num, "big_shift_explainer"),
                        )
                        entry.plan_context = enriched_context
                        entry.status = "planned"
                        entry.post_package_id = None  # reset - will be set by orchestrator
                    else:
                        entry = ContentCalendarEntry(
                            date=entry_date,
                            day_of_week=day_num,
                            angle_type=story.get(
                                "angle_type",
                                DEFAULT_CADENCE.get(day_num, "big_shift_explainer"),
                            ),
                            topic=story.get("topic"),
                            status="planned",
                            plan_context=enriched_context,
                        )
                        cal_db.add(entry)

                await cal_db.commit()
                logger.info(
                    "generate_week.calendar_entries_created",
                    week_start=str(week_start),
                    count=len(days_list),
                )

            # --- Phase 2: Daily Content for each day ---
            status["phase"] = "generating_days"
            daily_steps = WORKFLOWS["daily_from_plan"]
            days = weekly_plan.get("days", [])
            day_run_ids: list[str] = []
            day_package_ids: list[str] = []
            await _save()

            # Pre-fetch active templates for resolving template_id in daily briefs
            async with async_session() as tpl_db:
                tpl_result = await tpl_db.execute(
                    select(PatternTemplate).where(
                        PatternTemplate.status.in_(["active", "provisional"])
                    )
                )
                _templates_cache = [
                    {
                        "template_name": t.template_name,
                        "template_family": t.template_family,
                        "hook_formula": t.hook_formula,
                        "body_formula": t.body_formula,
                        "anti_patterns": t.anti_patterns,
                    }
                    for t in tpl_result.scalars().all()
                ]

            # Load founder voice profile for daily writers
            _founder_voice: dict = {}
            try:
                from tce.models.founder_voice_profile import FounderVoiceProfile

                async with async_session() as fv_db:
                    fv_result = await fv_db.execute(
                        select(FounderVoiceProfile).order_by(
                            FounderVoiceProfile.created_at.desc()
                        ).limit(1)
                    )
                    fv = fv_result.scalar_one_or_none()
                    if fv:
                        _founder_voice = {
                            "recurring_themes": fv.recurring_themes or [],
                            "values_and_beliefs": fv.values_and_beliefs or [],
                            "taboos": fv.taboos or [],
                            "tone_range": fv.tone_range or {},
                            "humor_type": fv.humor_type,
                            "metaphor_families": fv.metaphor_families or [],
                        }
            except Exception:
                pass  # Non-critical - proceed without voice profile

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
                        "evidence_requirements", "template_id",
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
                        "founder_voice": _founder_voice,
                    }

                    # Resolve template name to full formulas for writers
                    _tpl_name = story_brief.get("template_id")
                    if _tpl_name and _templates_cache:
                        _tpl_match = next(
                            (t for t in _templates_cache if t["template_name"] == _tpl_name),
                            None,
                        )
                        if _tpl_match:
                            day_context["_resolved_template"] = _tpl_match

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
                # Collect PostPackage ID for script pre-generation
                pkg_id = day_result.get("context", {}).get("_post_package_id")
                if pkg_id:
                    day_package_ids.append(str(pkg_id))

            status["day_run_ids"] = day_run_ids
            await _save()

            # --- Phase 3: Build the weekly guide with quality gate ---
            from tce.models.weekly_guide import WeeklyGuide
            from tce.services.guide_assessor import (
                MAX_ITERATIONS,
                QUALITY_THRESHOLD,
                assess_guide_content,
                build_feedback_prompt,
            )

            all_story_briefs = [d.get("story_brief", {}) for d in days]
            guide_context = {
                **request.context,
                "weekly_theme": weekly_theme,
                "gift_theme": gift_theme,
                "weekly_keyword": weekly_keyword,
                "story_briefs": all_story_briefs,
                "weekly_plan": weekly_plan,
            }

            best_composite = 0.0
            guide_id_str = None

            for attempt in range(1, MAX_ITERATIONS + 1):
                status["phase"] = "building_guide"
                if attempt == 1:
                    status["phase_detail"] = f"Building weekly guide (attempt {attempt}/{MAX_ITERATIONS})..."
                else:
                    status["phase_detail"] = (
                        f"Reiterating guide (attempt {attempt}/{MAX_ITERATIONS}, "
                        f"previous score: {best_composite:.1f}/10)..."
                    )
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

                # Get the saved guide ID
                guide_id_str = guide_result.get("context", {}).get("_weekly_guide_id")
                if not guide_id_str:
                    logger.warning("generate_week.no_guide_id", attempt=attempt)
                    break

                # Assess quality
                status["phase_detail"] = f"Assessing guide quality (attempt {attempt})..."
                await _save()

                async with async_session() as assess_db:
                    guide_obj = await assess_db.get(
                        WeeklyGuide, uuid.UUID(str(guide_id_str))
                    )
                    if not guide_obj or not guide_obj.markdown_content:
                        logger.warning("generate_week.guide_not_found", attempt=attempt)
                        break

                    try:
                        scores = await assess_guide_content(
                            markdown_content=guide_obj.markdown_content,
                            guide_title=guide_obj.guide_title,
                            settings=settings,
                            db=assess_db,
                        )
                    except Exception as ae:
                        logger.exception("generate_week.assess_failed", attempt=attempt)
                        scores = {"error": str(ae), "composite": 0}

                    composite = scores.get("composite", 0.0)
                    best_composite = composite

                    # Update guide with assessment
                    history = guide_obj.assessment_history or []
                    history.append({"iteration": attempt, **scores})
                    guide_obj.assessment_history = history
                    guide_obj.iteration_count = attempt
                    guide_obj.quality_scores = scores

                    if composite >= QUALITY_THRESHOLD:
                        guide_obj.quality_gate_passed = True
                        await assess_db.commit()
                        status["phase_detail"] = (
                            f"Guide passed quality gate! Score: {composite:.1f}/10 "
                            f"(attempt {attempt})"
                        )
                        await _save()
                        break
                    elif attempt == MAX_ITERATIONS:
                        guide_obj.quality_gate_passed = False
                        await assess_db.commit()
                        status["phase_detail"] = (
                            f"Guide capped at {MAX_ITERATIONS} iterations. "
                            f"Best score: {composite:.1f}/10."
                        )
                        await _save()
                    else:
                        guide_obj.quality_gate_passed = None
                        await assess_db.commit()
                        # Build feedback for next iteration
                        feedback = build_feedback_prompt(scores, attempt)
                        guide_context["_quality_feedback"] = feedback
                        guide_context["_existing_guide_id"] = str(guide_id_str)
                        status["phase_detail"] = (
                            f"Guide scored {composite:.1f}/10 (below {QUALITY_THRESHOLD}). "
                            f"Reiterating..."
                        )
                        await _save()

            status["guide_run_id"] = str(guide_run_id)

            # --- Phase 4: Pre-generate scripts for all days ---
            if day_package_ids:
                status["phase"] = "scripts"
                status["phase_detail"] = (
                    f"Pre-generating narration scripts for {len(day_package_ids)} days..."
                )
                await _save()

                from tce.api.routers.narration import GenerateScriptRequest, generate_script

                for si, pkg_id in enumerate(day_package_ids):
                    status["phase_detail"] = (
                        f"Generating script {si + 1}/{len(day_package_ids)}..."
                    )
                    await _save()
                    try:
                        async with async_session() as script_db:
                            req = GenerateScriptRequest(package_id=pkg_id)
                            await generate_script(req, script_db)
                        logger.info(
                            "script_pregeneration.done",
                            day=si,
                            package_id=pkg_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "script_pregeneration.failed",
                            day=si,
                            package_id=pkg_id,
                            error=str(e),
                        )
                        # Non-fatal - script can still be generated on-demand

            # --- Done ---
            status["phase"] = "completed"
            status["phase_detail"] = (
                f"All {len(day_package_ids) or 5} days + guide + scripts generated. "
                f"Guide score: {best_composite:.1f}/10"
            )
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
        "started_at": datetime.now(timezone.utc).isoformat(),
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
        status = dict(_week_generation[week_id])  # shallow copy for enrichment
        # Enrich with live agent-level detail from active orchestrators
        status = _enrich_week_status(status)
        return status

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


def _enrich_week_status(status: dict[str, Any]) -> dict[str, Any]:
    """Enrich week generation status with live agent step data.

    Inlines step_status, step_logs, and current_agents from the active
    orchestrator so the frontend doesn't need a separate sub-poll.
    """
    phase = status.get("phase", "")
    current_day = status.get("current_day", -1)
    day_run_ids = status.get("day_run_ids", [])

    # During day generation - inline the current day's orchestrator status
    if phase == "generating_days" and current_day >= 0:
        run_id = None
        if current_day < len(day_run_ids) and day_run_ids[current_day]:
            run_id = day_run_ids[current_day]
        if run_id and run_id in _active_runs:
            inner = _active_runs[run_id].get_status()
            step_status = inner.get("step_status", {})
            step_logs = inner.get("step_logs", {})
            status["day_step_status"] = step_status
            # Last 3 log entries per agent (keeps payload small)
            status["day_step_logs"] = {k: v[-3:] for k, v in step_logs.items()}
            running = [k for k, v in step_status.items() if v == "running"]
            status["current_agents"] = running

    # During planning - inline the planner orchestrator status
    elif phase == "planning":
        planner_id = status.get("planner_run_id")
        if planner_id and planner_id in _active_runs:
            inner = _active_runs[planner_id].get_status()
            status["planner_step_status"] = inner.get("step_status", {})
            status["planner_step_logs"] = {k: v[-3:] for k, v in inner.get("step_logs", {}).items()}

    # During guide building - inline the guide orchestrator status
    elif phase == "building_guide":
        guide_id = status.get("guide_run_id")
        if guide_id and guide_id in _active_runs:
            inner = _active_runs[guide_id].get_status()
            status["guide_step_status"] = inner.get("step_status", {})
            status["guide_step_logs"] = {k: v[-3:] for k, v in inner.get("step_logs", {}).items()}

    return status


# ---------------------------------------------------------------------------
# "Start From Topic" — generate a post from a user-specified topic
# ---------------------------------------------------------------------------

@router.post("/start-from-topic")
async def start_from_topic(
    request: StartFromTopicRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate content from a user-specified topic with optional inspiration.

    Runs the full daily_content pipeline but forces the topic through so
    trend_scout and story_strategist respect the user's intent.

    Optional: inspire_by_creator_ids loads creator style data,
    inspire_by_post_id loads a specific post as a writing reference.
    """
    from tce.models.creator_profile import CreatorProfile
    from tce.models.post_example import PostExample as PostExampleModel

    run_id = str(uuid.uuid4())

    # Build the creator_inspiration context if requested
    creator_inspiration: dict[str, Any] | None = None

    if request.inspire_by_post_id:
        post = await db.get(PostExampleModel, uuid.UUID(request.inspire_by_post_id))
        if not post:
            raise HTTPException(status_code=404, detail="Post example not found")
        creator_name = "Unknown"
        if post.creator_id:
            creator = await db.get(CreatorProfile, post.creator_id)
            if creator:
                creator_name = creator.creator_name
        creator_inspiration = {
            "creator_name": creator_name,
            "post_text": post.post_text_raw or post.hook_text or "",
            "hook_type": post.hook_type or "unknown",
            "body_structure": post.body_structure or "unknown",
            "story_arc": post.story_arc or "unknown",
            "cta_type": post.cta_type or "unknown",
            "tone_tags": post.tone_tags or [],
            "topic_tags": post.topic_tags or [],
            "word_count": len((post.post_text_raw or "").split()),
            "influence_weight": 30,
            "style_notes": "",
        }
    elif request.inspire_by_creator_ids:
        # Load creator profiles and their top-scoring post
        creators = []
        best_post = None
        best_score = -1
        for cid in request.inspire_by_creator_ids[:3]:  # Max 3 creators
            creator = await db.get(CreatorProfile, uuid.UUID(cid))
            if creator:
                creators.append(creator)
                # Find their highest-scoring post
                result = await db.execute(
                    select(PostExampleModel)
                    .where(PostExampleModel.creator_id == creator.id)
                    .order_by(PostExampleModel.final_score.desc().nulls_last())
                    .limit(1)
                )
                top_post = result.scalar_one_or_none()
                if top_post and (top_post.final_score or 0) > best_score:
                    best_post = top_post
                    best_score = top_post.final_score or 0

        if creators and best_post:
            creator_names = ", ".join(c.creator_name for c in creators)
            style_notes_parts = [c.style_notes or "" for c in creators if c.style_notes]
            creator_inspiration = {
                "creator_name": creator_names,
                "post_text": best_post.post_text_raw or best_post.hook_text or "",
                "hook_type": best_post.hook_type or "unknown",
                "body_structure": best_post.body_structure or "unknown",
                "story_arc": best_post.story_arc or "unknown",
                "cta_type": best_post.cta_type or "unknown",
                "tone_tags": best_post.tone_tags or [],
                "topic_tags": best_post.topic_tags or [],
                "word_count": len((best_post.post_text_raw or "").split()),
                "influence_weight": min(20 * len(creators), 40),
                "style_notes": "; ".join(style_notes_parts),
            }

    # Build pipeline context
    context: dict[str, Any] = {
        "topic": request.topic,
        "language": request.language,
    }
    if request.template_hint:
        context["template_hint"] = request.template_hint
    if request.cta_keyword:
        context["weekly_keyword"] = request.cta_keyword
    if request.notes:
        context["operator_overrides"] = {"notes": request.notes}
    if creator_inspiration:
        context["creator_inspiration"] = creator_inspiration

    # Store status for polling
    _start_topic_runs[run_id] = {
        "run_id": run_id,
        "status": "running",
        "phase": "starting",
        "phase_detail": "Initializing topic-based generation...",
        "pipeline_run_id": None,
        "step_status": {},
        "error": None,
        "topic": request.topic[:200],
        "inspiration": creator_inspiration.get("creator_name") if creator_inspiration else None,
    }
    await _persist_start_topic_status(run_id, _start_topic_runs[run_id])

    async def _run_topic() -> None:
        from tce.db.session import async_session

        status = _start_topic_runs[run_id]

        async def _save() -> None:
            await _persist_start_topic_status(run_id, status)

        try:
            status["phase"] = "running"
            status["phase_detail"] = "Running daily_content pipeline with your topic..."
            await _save()

            pipeline_run_id = uuid.uuid4()

            async with async_session() as pipe_db:
                run_record = PipelineRun(
                    run_id=pipeline_run_id,
                    workflow="daily_content",
                    status="running",
                    started_at=datetime.utcnow(),
                )
                pipe_db.add(run_record)
                await pipe_db.commit()
                record_id = run_record.id

                steps = WORKFLOWS["daily_content"]
                orchestrator = PipelineOrchestrator(
                    steps=steps,
                    db=pipe_db,
                    settings=settings,
                    run_id=pipeline_run_id,
                )
                _active_runs[str(pipeline_run_id)] = orchestrator
                status["pipeline_run_id"] = str(pipeline_run_id)
                await _save()

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
                        run_record.error_message = "; ".join(
                            f"{k}: {v}" for k, v in errors.items()
                        )
                    await bk_db.commit()

            _active_runs.pop(str(pipeline_run_id), None)

            status["phase"] = "completed"
            status["phase_detail"] = "Content generated from your topic"
            status["status"] = "completed"
            status["pipeline_run_id"] = str(pipeline_run_id)
            status["step_status"] = result.get("step_status", {})
            await _save()

        except Exception as e:
            logger.exception("start_from_topic.error", run_id=run_id)
            status["phase"] = "failed"
            status["error"] = str(e)
            status["status"] = "failed"
            await _save()

    asyncio.create_task(_run_topic())

    return {
        "run_id": run_id,
        "status": "started",
        "status_url": f"/api/v1/pipeline/start-from-topic/{run_id}/status",
        "topic": request.topic[:200],
        "inspiration": creator_inspiration.get("creator_name") if creator_inspiration else None,
    }


_start_topic_runs: dict[str, dict] = {}


async def _persist_start_topic_status(run_id: str, status: dict) -> None:
    """Persist start-from-topic run status to the polish_run_status table (reuse)."""
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
        logger.warning("persist_start_topic_status.failed", run_id=run_id, exc_info=True)


@router.get("/start-from-topic/{run_id}/status")
async def get_start_from_topic_status(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get status of a start-from-topic run."""
    if run_id in _start_topic_runs:
        status = _start_topic_runs[run_id]
        pipe_id = status.get("pipeline_run_id")
        if pipe_id and pipe_id in _active_runs:
            live = _active_runs[pipe_id].get_status()
            status["step_status"] = live.get("step_status", status.get("step_status", {}))
            status["step_logs"] = live.get("step_logs", {})
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
            db_status["phase_detail"] = "Server restarted - generation was interrupted"
            await _persist_start_topic_status(run_id, db_status)
        return db_status

    raise HTTPException(status_code=404, detail="Start-from-topic run not found")


# ---------------------------------------------------------------------------
# Inspiration selectors — list creators and top posts for UI combo/selector
# ---------------------------------------------------------------------------

@router.get("/inspiration/creators")
async def list_inspiration_creators(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List creators available for inspiration, with post counts and top engagement.

    Returns creators sorted by total engagement (comments + shares) descending.
    Used by the UI to populate the "inspire by creator" combo selector.
    """
    from tce.models.creator_profile import CreatorProfile
    from tce.models.post_example import PostExample as PostExampleModel

    result = await db.execute(select(CreatorProfile).order_by(CreatorProfile.creator_name))
    creators = list(result.scalars().all())

    out = []
    for c in creators:
        posts_result = await db.execute(
            select(PostExampleModel).where(PostExampleModel.creator_id == c.id)
        )
        posts = list(posts_result.scalars().all())
        total_comments = sum(p.visible_comments or 0 for p in posts)
        total_shares = sum(p.visible_shares or 0 for p in posts)
        out.append({
            "id": str(c.id),
            "creator_name": c.creator_name,
            "style_notes": c.style_notes,
            "post_count": len(posts),
            "total_comments": total_comments,
            "total_shares": total_shares,
            "total_engagement": total_comments + total_shares,
            "top_patterns": c.top_patterns,
        })

    out.sort(key=lambda x: x["total_engagement"], reverse=True)
    return out


@router.get("/inspiration/posts")
async def list_inspiration_posts(
    creator_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List posts available for inspiration, sorted by comments descending.

    Optionally filter by creator_id. Used by the UI to populate the
    "inspire by post" selector. Shows hook text preview and engagement stats.
    """
    from tce.models.creator_profile import CreatorProfile
    from tce.models.post_example import PostExample as PostExampleModel

    query = (
        select(PostExampleModel)
        .order_by(PostExampleModel.visible_comments.desc().nulls_last())
        .limit(min(limit, 200))
    )
    if creator_id:
        query = query.where(PostExampleModel.creator_id == uuid.UUID(creator_id))

    result = await db.execute(query)
    posts = list(result.scalars().all())

    # Batch-load creator names
    creator_ids = set(p.creator_id for p in posts if p.creator_id)
    creator_map = {}
    if creator_ids:
        cr_result = await db.execute(
            select(CreatorProfile).where(CreatorProfile.id.in_(creator_ids))
        )
        for cr in cr_result.scalars().all():
            creator_map[cr.id] = cr.creator_name

    out = []
    for p in posts:
        hook_preview = (p.hook_text or p.post_text_raw or "")[:150]
        out.append({
            "id": str(p.id),
            "creator_name": creator_map.get(p.creator_id, "Unknown"),
            "hook_preview": hook_preview,
            "hook_type": p.hook_type,
            "body_structure": p.body_structure,
            "story_arc": p.story_arc,
            "visible_comments": p.visible_comments,
            "visible_shares": p.visible_shares,
            "final_score": p.final_score,
            "visual_type": p.visual_type,
            "visual_description": p.visual_description,
        })

    return out


# ---------------------------------------------------------------------------
# "Start From Copy" — polish user-provided copy into a full package
# ---------------------------------------------------------------------------

class StartFromTopicRequest(BaseModel):
    """Generate a post from a user-specified topic with optional creator/post inspiration."""
    topic: str  # Required: what the post should be about
    template_hint: str | None = None  # e.g. "big_shift_explainer"
    inspire_by_creator_ids: list[str] = []  # Creator profile UUIDs (combo select)
    inspire_by_post_id: str | None = None  # Specific post example UUID
    cta_keyword: str | None = None
    language: str = "english"
    notes: str | None = None


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
    """Senior Strategist brainstorm - rich context + web search + tool use.

    Loads full package context (brief, research, guide, template, posts).
    Uses Sonnet with Claude tool_use for web search and package lookup.
    """
    from tce.models.post_package import PostPackage
    from tce.models.research_brief import ResearchBrief
    from tce.models.story_brief import StoryBrief
    from tce.models.weekly_guide import WeeklyGuide
    from tce.services.web_search import WebSearchService

    # --- Build rich context ---
    context_parts: list[str] = []

    pkg = None
    if request.package_id:
        try:
            pkg = await db.get(PostPackage, request.package_id)
        except Exception:
            logger.warning("brainstorm.package_load_failed", package_id=request.package_id)

    if pkg:
        # Posts
        if pkg.facebook_post:
            context_parts.append(f"FACEBOOK POST:\n{pkg.facebook_post}")
        if pkg.linkedin_post:
            context_parts.append(f"LINKEDIN POST:\n{pkg.linkedin_post}")
        if pkg.hook_variants:
            context_parts.append(f"HOOK VARIANTS:\n" + "\n".join(f"- {h}" for h in pkg.hook_variants))
        if pkg.cta_keyword:
            context_parts.append(f"CTA KEYWORD: {pkg.cta_keyword}")
        if pkg.image_prompts:
            prompts = pkg.image_prompts if isinstance(pkg.image_prompts, list) else []
            names = [p.get("prompt_name", "unnamed") for p in prompts[:5]]
            context_parts.append(f"IMAGE CONCEPTS: {', '.join(names)}")

        # Story brief
        if pkg.brief_id:
            brief = await db.get(StoryBrief, pkg.brief_id)
            if brief:
                brief_lines = [f"STORY BRIEF:"]
                for field in ("topic", "audience", "angle_type", "thesis", "desired_belief_shift", "evidence_requirements", "cta_goal", "visual_job"):
                    val = getattr(brief, field, None)
                    if val:
                        brief_lines.append(f"  {field}: {val}")
                if brief.house_voice_weights:
                    brief_lines.append(f"  voice_weights: {json.dumps(brief.house_voice_weights)}")
                context_parts.append("\n".join(brief_lines))

        # Research brief
        if pkg.research_brief_id:
            research = await db.get(ResearchBrief, pkg.research_brief_id)
            if research:
                res_lines = ["RESEARCH BRIEF:"]
                if research.verified_claims:
                    res_lines.append(f"  Verified claims: {json.dumps(research.verified_claims)}")
                if research.uncertain_claims:
                    res_lines.append(f"  Uncertain claims: {json.dumps(research.uncertain_claims)}")
                if research.source_refs:
                    res_lines.append(f"  Sources: {json.dumps(research.source_refs)}")
                if research.risk_flags:
                    res_lines.append(f"  Risk flags: {json.dumps(research.risk_flags)}")
                context_parts.append("\n".join(res_lines))

        # Weekly guide
        if pkg.weekly_guide_id:
            guide = await db.get(WeeklyGuide, pkg.weekly_guide_id)
            if guide:
                guide_lines = [f"WEEKLY GUIDE: {guide.guide_title}"]
                guide_lines.append(f"  Theme: {guide.weekly_theme}")
                if guide.cta_keyword:
                    guide_lines.append(f"  Guide CTA: {guide.cta_keyword}")
                context_parts.append("\n".join(guide_lines))

        # Template from quality_scores
        qs = pkg.quality_scores or {}
        tpl = qs.get("matched_template")
        if tpl:
            tpl_lines = [f"MATCHED TEMPLATE: {tpl.get('template_name', '?')} ({tpl.get('template_family', '?')})"]
            if tpl.get("hook_formula"):
                tpl_lines.append(f"  Hook formula: {tpl['hook_formula']}")
            if tpl.get("body_formula"):
                tpl_lines.append(f"  Body formula: {tpl['body_formula']}")
            context_parts.append("\n".join(tpl_lines))

        # Quality scores summary
        if qs.get("overall_score"):
            context_parts.append(f"QUALITY SCORE: {qs['overall_score']}")

    context_block = "\n\n".join(context_parts) if context_parts else "(No package loaded)"

    system_prompt = (
        "You are the Senior Content Strategist for Team Content Engine - the highest-ranking "
        "advisor on the team. You have full authority to:\n"
        "- Search the web for facts, dates, statistics, and competitor analysis\n"
        "- Access all content packages, briefs, research, templates, and guides\n"
        "- Fact-check any claim before it goes into a post\n"
        "- Suggest alternative angles backed by real data\n\n"
        "Be concise, creative, and actionable. No fluff. When the operator asks about dates, "
        "facts, statistics, or competitors - USE your web_search tool. Don't say 'I don't have access.' You DO.\n\n"
        f"CURRENT PACKAGE CONTEXT:\n{context_block}"
    )

    # --- Define tools ---
    tools = [
        {
            "name": "web_search",
            "description": "Search the web for facts, dates, news, statistics, competitor analysis, or any external information. Use this whenever the user asks about something you need to verify or look up.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "lookup_packages",
            "description": "Look up recent content packages to see what else was generated. Useful for checking what topics were already covered or finding patterns.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "description": "How many days back to look (default 7)", "default": 7},
                },
            },
        },
    ]

    # --- Build messages from history ---
    messages: list[dict[str, Any]] = []
    for msg in request.history[-20:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": request.message})

    # --- Call Sonnet with tool_use ---
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    response = await client.messages.create(
        model=settings.default_model,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
        tools=tools,
    )

    tool_calls_made: list[dict[str, Any]] = []
    max_tool_rounds = 5

    while response.stop_reason == "tool_use" and max_tool_rounds > 0:
        max_tool_rounds -= 1
        tool_results = []

        for block in response.content:
            if block.type == "tool_use":
                if block.name == "web_search":
                    query = block.input.get("query", "")
                    logger.info("brainstorm.web_search", query=query)
                    search_svc = WebSearchService()
                    results = await search_svc.search(query, count=5)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(results[:5]),
                    })
                    tool_calls_made.append({"tool": "web_search", "query": query})

                elif block.name == "lookup_packages":
                    days = block.input.get("days_back", 7)
                    logger.info("brainstorm.lookup_packages", days_back=days)
                    cutoff = datetime.utcnow() - timedelta(days=days)
                    pkg_result = await db.execute(
                        select(PostPackage)
                        .where(PostPackage.created_at >= cutoff)
                        .order_by(PostPackage.created_at.desc())
                        .limit(20)
                    )
                    recent_pkgs = pkg_result.scalars().all()
                    summaries = []
                    for rp in recent_pkgs:
                        s = {"id": str(rp.id), "created": str(rp.created_at)}
                        if rp.quality_scores and rp.quality_scores.get("matched_template"):
                            s["template"] = rp.quality_scores["matched_template"].get("template_name")
                        fb_preview = (rp.facebook_post or "")[:120]
                        if fb_preview:
                            s["fb_preview"] = fb_preview
                        if rp.cta_keyword:
                            s["cta"] = rp.cta_keyword
                        summaries.append(s)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(summaries),
                    })
                    tool_calls_made.append({"tool": "lookup_packages", "days_back": days})

        # Send tool results back for next round
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        response = await client.messages.create(
            model=settings.default_model,
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )

    reply = "".join(b.text for b in response.content if hasattr(b, "text"))
    if not reply:
        reply = "I couldn't generate a response."

    return {
        "reply": reply,
        "model": settings.default_model,
        "tool_calls_made": tool_calls_made,
    }


# --- Video Lead Scripts ---


@router.get("/video-lead-scripts")
async def list_video_lead_scripts(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all video lead scripts, newest first."""
    from sqlalchemy import desc
    result = await db.execute(
        select(VideoLeadScript)
        .order_by(desc(VideoLeadScript.created_at))
        .limit(limit)
    )
    scripts = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "title": s.title,
            "title_pattern": s.title_pattern,
            "word_count": s.word_count,
            "estimated_duration_minutes": s.estimated_duration_minutes,
            "niche": s.niche,
            "status": s.status,
            "topic": s.topic,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in scripts
    ]


@router.get("/video-lead-scripts/{script_id}")
async def get_video_lead_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single video lead script with full content."""
    result = await db.execute(
        select(VideoLeadScript).where(VideoLeadScript.id == uuid.UUID(script_id))
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Script not found")
    return {
        "id": str(s.id),
        "title": s.title,
        "title_pattern": s.title_pattern,
        "hook": s.hook,
        "full_script": s.full_script,
        "sections": s.sections,
        "word_count": s.word_count,
        "estimated_duration_minutes": s.estimated_duration_minutes,
        "target_audience": s.target_audience,
        "key_takeaway": s.key_takeaway,
        "niche": s.niche,
        "seo_description": s.seo_description,
        "tags": s.tags,
        "blog_repurpose_outline": s.blog_repurpose_outline,
        "status": s.status,
        "topic": s.topic,
        "thesis": s.thesis,
        "pipeline_run_id": str(s.pipeline_run_id) if s.pipeline_run_id else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
