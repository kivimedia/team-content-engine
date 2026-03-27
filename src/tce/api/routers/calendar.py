"""Content calendar endpoints (PRD Section 43.3)."""

import asyncio
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.content_calendar import ContentCalendarEntry
from tce.schemas.content_calendar import (
    ContentCalendarRead,
    ContentCalendarUpdate,
    PlanApproveRequest,
    PlanWeekDeepRequest,
    PlanWeekRequest,
)
from tce.settings import Settings, settings

logger = structlog.get_logger()

router = APIRouter(prefix="/calendar", tags=["calendar"])

# Default 5-day cadence (PRD Section 9.5)
DEFAULT_CADENCE = {
    0: "big_shift_explainer",
    1: "tactical_workflow_guide",
    2: "contrarian_diagnosis",
    3: "case_study_build_story",
    4: "second_order_implication",
}


@router.get("/", response_model=list[ContentCalendarRead])
async def list_calendar(
    start: date | None = None,
    end: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ContentCalendarEntry]:
    """List calendar entries, optionally filtered by date range."""
    query = select(ContentCalendarEntry).order_by(
        ContentCalendarEntry.date
    )
    if start:
        query = query.where(ContentCalendarEntry.date >= start)
    if end:
        query = query.where(ContentCalendarEntry.date <= end)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/today", response_model=ContentCalendarRead | None)
async def get_today(
    db: AsyncSession = Depends(get_db),
):
    """Get today's calendar entry."""
    result = await db.execute(
        select(ContentCalendarEntry).where(
            ContentCalendarEntry.date == date.today()
        )
    )
    return result.scalar_one_or_none()


@router.post("/plan-week", response_model=list[ContentCalendarRead])
async def plan_week(
    request: PlanWeekRequest,
    db: AsyncSession = Depends(get_db),
) -> list[ContentCalendarEntry]:
    """Generate 5 calendar entries (Mon-Fri) for a given week."""
    entries = []
    for day_offset in range(5):
        entry_date = request.week_start + timedelta(days=day_offset)
        # Check if entry already exists
        existing = await db.execute(
            select(ContentCalendarEntry).where(
                ContentCalendarEntry.date == entry_date
            )
        )
        if existing.scalar_one_or_none():
            continue

        angle = DEFAULT_CADENCE.get(day_offset, "big_shift_explainer")
        entry = ContentCalendarEntry(
            date=entry_date,
            day_of_week=day_offset,
            angle_type=angle,
            status="planned",
        )
        db.add(entry)
        entries.append(entry)

    await db.flush()

    # Store weekly_theme for pipeline context (PRD Section 15.2)
    if request.weekly_theme and entries:
        for entry in entries:
            entry.operator_notes = (
                f"Weekly theme: {request.weekly_theme}"
            )
        await db.flush()

    # Generate topics for each day using a quick LLM call
    if entries:
        await _generate_topics(entries, request.weekly_theme)
        await db.flush()

    return entries


ANGLE_DESCRIPTIONS = {
    "big_shift_explainer": "Make a fast-moving AI development legible and relevant",
    "tactical_workflow_guide": "Deliver immediate utility with a repeatable process",
    "contrarian_diagnosis": "Challenge a lazy or outdated assumption",
    "case_study_build_story": "Show proof through a real workflow or teardown",
    "second_order_implication": "Explain consequences others aren't discussing",
}


async def _generate_topics(
    entries: list[ContentCalendarEntry], weekly_theme: str | None
) -> None:
    """Use a quick LLM call to generate one-line topics for each day."""
    try:
        import anthropic

        settings = Settings()
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        days_info = []
        for entry in entries:
            desc = ANGLE_DESCRIPTIONS.get(entry.angle_type, entry.angle_type)
            days_info.append(
                f"- {['Monday','Tuesday','Wednesday','Thursday','Friday'][entry.day_of_week]}: "
                f"template={entry.angle_type} ({desc})"
            )

        theme_line = f"Weekly theme: {weekly_theme}" if weekly_theme else "No specific theme - pick trending AI/business topics"

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            temperature=0.7,
            messages=[{
                "role": "user",
                "content": (
                    f"{theme_line}\n\n"
                    f"Generate a specific, compelling one-line topic for each day's post. "
                    f"Each topic should be concrete (mention real companies, tools, or trends) "
                    f"and match the template style.\n\n"
                    f"Days:\n" + "\n".join(days_info) + "\n\n"
                    f"Reply with ONLY a JSON object: {{\"0\": \"topic\", \"1\": \"topic\", ...}} "
                    f"where keys are day indices (0=Mon, 4=Fri). No markdown."
                ),
            }],
        )

        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        topics = json.loads(text)

        for entry in entries:
            topic = topics.get(str(entry.day_of_week))
            if topic:
                entry.topic = topic

        logger.info("calendar.topics_generated", count=len(entries))
    except Exception:
        logger.exception("calendar.topic_generation_failed")
        # Non-fatal - entries still exist, just without topics


@router.get("/buffers", response_model=list[ContentCalendarRead])
async def list_buffers(
    db: AsyncSession = Depends(get_db),
) -> list[ContentCalendarEntry]:
    """List available buffer/backup posts (PRD Section 43.3)."""
    result = await db.execute(
        select(ContentCalendarEntry)
        .where(ContentCalendarEntry.is_buffer.is_(True))
        .order_by(ContentCalendarEntry.buffer_priority.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/{entry_id}/set-buffer",
    response_model=ContentCalendarRead,
)
async def set_buffer(
    entry_id: uuid.UUID,
    priority: int = 1,
    db: AsyncSession = Depends(get_db),
) -> ContentCalendarEntry:
    """Mark a calendar entry as a buffer post."""
    entry = await db.get(ContentCalendarEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry.is_buffer = True
    entry.buffer_priority = priority
    await db.flush()
    return entry


@router.patch("/{entry_id}", response_model=ContentCalendarRead)
async def update_entry(
    entry_id: uuid.UUID,
    data: ContentCalendarUpdate,
    db: AsyncSession = Depends(get_db),
) -> ContentCalendarEntry:
    """Update a calendar entry (topic, status, notes)."""
    entry = await db.get(ContentCalendarEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    await db.flush()
    return entry


# ---------------------------------------------------------------------------
# Deep Planning (human-in-the-loop weekly planning)
# ---------------------------------------------------------------------------

_deep_plans: dict[str, dict[str, Any]] = {}


@router.post("/plan-week-deep")
async def plan_week_deep(
    request: PlanWeekDeepRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run the weekly_planner (trend scout + strategy) and return a plan for review."""
    plan_id = str(uuid.uuid4())

    _deep_plans[plan_id] = {
        "plan_id": plan_id,
        "status": "running",
        "phase": "starting",
        "phase_detail": "Initializing weekly planning...",
        "week_start": request.week_start.isoformat(),
        "weekly_plan": None,
        "trend_brief": None,
        "error": None,
        "started_at": datetime.utcnow().isoformat(),
    }

    async def _run_deep_plan() -> None:
        from tce.db.session import async_session
        from tce.orchestrator.engine import PipelineOrchestrator
        from tce.orchestrator.workflows import WORKFLOWS

        status = _deep_plans[plan_id]

        async with async_session() as bg_db:
            try:
                status["phase"] = "trend_research"
                status["phase_detail"] = "Running trend research across AI, tech, and business..."

                planner_steps = WORKFLOWS["weekly_planner"]
                run_id = uuid.uuid4()

                context: dict[str, Any] = {}
                if request.weekly_theme:
                    context["weekly_theme"] = request.weekly_theme
                if request.focus_areas:
                    context["focus_areas"] = request.focus_areas

                orch = PipelineOrchestrator(
                    steps=planner_steps,
                    db=bg_db,
                    settings=settings,
                    run_id=run_id,
                )

                # Hook into progress to update status
                original_report = None
                if hasattr(orch, '_progress_log'):
                    pass  # Will check progress via result

                status["phase"] = "strategist"
                status["phase_detail"] = "Strategist choosing 5 topics, gift theme, and CTA keyword..."

                result = await orch.run(context)
                await bg_db.commit()

                ctx = result.get("context", {})
                weekly_plan = ctx.get("weekly_plan", {})
                trend_brief = ctx.get("trend_brief", {})

                if not weekly_plan or not weekly_plan.get("days"):
                    status["status"] = "failed"
                    status["phase"] = "failed"
                    status["error"] = "Weekly planner did not produce a valid plan"
                    return

                # Create/update calendar entries
                week_plan_uuid = uuid.uuid4()
                for day_plan in weekly_plan.get("days", []):
                    day_num = day_plan.get("day_of_week", 0)
                    entry_date = request.week_start + timedelta(days=day_num)

                    # Check for existing entry
                    existing = await bg_db.execute(
                        select(ContentCalendarEntry).where(
                            ContentCalendarEntry.date == entry_date
                        )
                    )
                    entry = existing.scalar_one_or_none()

                    story_brief = day_plan.get("story_brief", day_plan)

                    if entry:
                        entry.topic = story_brief.get("topic", entry.topic)
                        entry.plan_context = story_brief
                        entry.weekly_plan_id = week_plan_uuid
                        entry.status = "planned"
                    else:
                        angle = DEFAULT_CADENCE.get(day_num, "big_shift_explainer")
                        entry = ContentCalendarEntry(
                            date=entry_date,
                            day_of_week=day_num,
                            angle_type=story_brief.get("angle_type", angle),
                            topic=story_brief.get("topic"),
                            status="planned",
                            plan_context=story_brief,
                            weekly_plan_id=week_plan_uuid,
                        )
                        bg_db.add(entry)

                await bg_db.commit()

                # Trim trend_brief for response (keep just headlines + scores)
                trend_summary = []
                for t in trend_brief.get("trends", [])[:10]:
                    trend_summary.append({
                        "headline": t.get("headline", ""),
                        "relevance_score": t.get("relevance_score", 0),
                        "source_url": t.get("source_url", ""),
                        "angle_suggestions": t.get("angle_suggestions", t.get("angles", [])),
                    })

                status["status"] = "completed"
                status["phase"] = "completed"
                status["phase_detail"] = "Plan ready for review"
                status["weekly_plan"] = weekly_plan
                status["weekly_plan_id"] = str(week_plan_uuid)
                status["trend_summary"] = trend_summary
                status["completed_at"] = datetime.utcnow().isoformat()

            except Exception as e:
                logger.exception("plan_week_deep.error", plan_id=plan_id)
                status["status"] = "failed"
                status["phase"] = "failed"
                status["error"] = str(e)

    asyncio.create_task(_run_deep_plan())

    return {
        "plan_id": plan_id,
        "status": "started",
        "status_url": f"/api/v1/calendar/plan-week-deep/{plan_id}/status",
    }


@router.get("/plan-week-deep/{plan_id}/status")
async def get_deep_plan_status(plan_id: str) -> dict[str, Any]:
    """Get the status of a deep planning run."""
    if plan_id not in _deep_plans:
        raise HTTPException(status_code=404, detail="Plan not found")
    return _deep_plans[plan_id]


@router.post("/plan-week-deep/{plan_id}/approve")
async def approve_deep_plan(
    plan_id: str,
    request: PlanApproveRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve (and optionally edit) the deep plan. Updates calendar entries."""
    if plan_id not in _deep_plans:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan_status = _deep_plans[plan_id]
    if plan_status["status"] != "completed":
        raise HTTPException(status_code=400, detail="Plan is not ready for approval")

    week_start_str = plan_status.get("week_start")
    if not week_start_str:
        raise HTTPException(status_code=400, detail="Plan missing week_start")

    week_start = date.fromisoformat(week_start_str)
    weekly_plan_id_str = plan_status.get("weekly_plan_id")

    # Update calendar entries with the (possibly edited) plan
    for day_plan in request.days:
        day_num = day_plan.get("day_of_week", 0)
        entry_date = week_start + timedelta(days=day_num)

        result = await db.execute(
            select(ContentCalendarEntry).where(
                ContentCalendarEntry.date == entry_date
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.topic = day_plan.get("topic", entry.topic)
            entry.plan_context = day_plan
            entry.status = "approved"
            entry.operator_notes = (
                f"Weekly theme: {request.weekly_theme} | "
                f"CTA: {request.cta_keyword} | "
                f"Gift: {request.gift_theme if isinstance(request.gift_theme, str) else request.gift_theme.get('title', '')}"
            )

    await db.flush()

    # Update the in-memory plan with approved edits
    plan_status["approved"] = True
    plan_status["approved_plan"] = {
        "weekly_theme": request.weekly_theme,
        "gift_theme": request.gift_theme,
        "cta_keyword": request.cta_keyword,
        "days": request.days,
    }

    return {
        "plan_id": plan_id,
        "status": "approved",
        "message": "Plan approved and calendar entries updated",
    }
