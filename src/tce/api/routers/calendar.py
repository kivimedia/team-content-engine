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

from tce.db.session import async_session, get_db
from tce.models.content_calendar import ContentCalendarEntry
from tce.models.guide_option import GuideOption
from tce.models.slot_option import SlotOption
from tce.models.weekly_plan import WeeklyPlan
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
    query = select(ContentCalendarEntry).order_by(ContentCalendarEntry.date)
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
        select(ContentCalendarEntry).where(ContentCalendarEntry.date == date.today())
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
            select(ContentCalendarEntry).where(ContentCalendarEntry.date == entry_date)
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
            entry.operator_notes = f"Weekly theme: {request.weekly_theme}"
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


async def _generate_topics(entries: list[ContentCalendarEntry], weekly_theme: str | None) -> None:
    """Use a quick LLM call to generate one-line topics for each day."""
    try:
        import anthropic

        settings = Settings()
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        days_info = []
        for entry in entries:
            desc = ANGLE_DESCRIPTIONS.get(entry.angle_type, entry.angle_type)
            days_info.append(
                f"- {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'][entry.day_of_week]}: "
                f"template={entry.angle_type} ({desc})"
            )

        theme_line = (
            f"Weekly theme: {weekly_theme}"
            if weekly_theme
            else "No specific theme - pick trending AI/business topics"
        )

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            temperature=0.7,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{theme_line}\n\n"
                        f"Generate a specific, compelling one-line topic for each day's post. "
                        f"Each topic should be concrete (mention real companies, tools, or trends) "
                        f"and match the template style.\n\n"
                        f"Days:\n" + "\n".join(days_info) + "\n\n"
                        'Reply with ONLY a JSON object: {"0": "topic", "1": "topic", ...} '
                        "where keys are day indices (0=Mon, 4=Fri). No markdown."
                    ),
                }
            ],
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

# In-memory cache for active plans (backed by DB for persistence)
_deep_plans_cache: dict[str, dict[str, Any]] = {}


async def _save_plan_to_db(plan_id: str, data: dict[str, Any]) -> None:
    """Persist plan state to DB (fire and forget from background task)."""
    async with async_session() as db:
        plan = await db.get(WeeklyPlan, uuid.UUID(plan_id))
        if plan:
            plan.status = data.get("status", "running")
            plan.plan_data = data
            plan.progress_log = data.get("phase_detail", "")
        await db.commit()


async def _load_plan_from_db(plan_id: str) -> dict[str, Any] | None:
    """Load plan from DB if not in cache."""
    async with async_session() as db:
        plan = await db.get(WeeklyPlan, uuid.UUID(plan_id))
        if plan and plan.plan_data:
            return plan.plan_data
    return None


async def _get_plan(plan_id: str) -> dict[str, Any] | None:
    """Get plan from cache, falling back to DB."""
    if plan_id in _deep_plans_cache:
        return _deep_plans_cache[plan_id]
    data = await _load_plan_from_db(plan_id)
    if data:
        _deep_plans_cache[plan_id] = data
    return data


@router.post("/plan-week-deep")
async def plan_week_deep(
    request: PlanWeekDeepRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run the weekly_planner (trend scout + strategy) and return a plan for review."""
    plan_id = str(uuid.uuid4())

    initial_data = {
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
    _deep_plans_cache[plan_id] = initial_data

    # Persist to DB immediately
    plan_row = WeeklyPlan(
        id=uuid.UUID(plan_id),
        status="running",
        plan_data=initial_data,
        week_start=request.week_start,
        run_id=uuid.uuid4(),
    )
    db.add(plan_row)
    await db.flush()

    async def _run_deep_plan() -> None:
        from tce.orchestrator.engine import PipelineOrchestrator
        from tce.orchestrator.workflows import WORKFLOWS

        status = _deep_plans_cache[plan_id]

        async with async_session() as bg_db:
            try:
                status["phase"] = "trend_research"
                status["phase_detail"] = "Running trend research across AI, tech, and business..."

                planner_steps = WORKFLOWS["weekly_planner"]
                run_id = uuid.uuid4()

                # === Load voice context for the planner ===
                from tce.models.creator_profile import CreatorProfile
                from tce.models.founder_voice_profile import FounderVoiceProfile

                context: dict[str, Any] = {}
                if request.weekly_theme:
                    context["weekly_theme"] = request.weekly_theme
                if request.focus_areas:
                    context["focus_areas"] = request.focus_areas
                if request.sensitive_period:
                    context["sensitive_period"] = True
                if request.humanitarian_context:
                    context["humanitarian_context"] = request.humanitarian_context
                _video_days = sorted(request.resolved_video_days())
                if _video_days:
                    # Canonical plural for agents
                    context["video_day_weekdays"] = _video_days
                    # Legacy singular for any code path still reading it
                    context["video_day_weekday"] = _video_days[0]

                # Load founder voice
                fv_result = await bg_db.execute(
                    select(FounderVoiceProfile).order_by(
                        FounderVoiceProfile.created_at.desc()
                    ).limit(1)
                )
                founder_voice = fv_result.scalar_one_or_none()
                if founder_voice:
                    context["founder_voice"] = {
                        "recurring_themes": founder_voice.recurring_themes or [],
                        "values_and_beliefs": founder_voice.values_and_beliefs or [],
                        "taboos": founder_voice.taboos or [],
                        "tone_range": founder_voice.tone_range or {},
                        "humor_type": founder_voice.humor_type,
                        "metaphor_families": founder_voice.metaphor_families or [],
                    }

                # Load creator profiles
                cr_result = await bg_db.execute(
                    select(CreatorProfile).order_by(CreatorProfile.creator_name)
                )
                creators = cr_result.scalars().all()
                if creators:
                    context["creator_profiles"] = [
                        {
                            "name": c.creator_name,
                            "style": c.style_notes,
                            "voice_axes": c.voice_axes,
                            "top_patterns": c.top_patterns,
                            "weight": c.allowed_influence_weight,
                        }
                        for c in creators
                        if c.voice_axes
                    ]

                orch = PipelineOrchestrator(
                    steps=planner_steps,
                    db=bg_db,
                    settings=settings,
                    run_id=run_id,
                )

                status["phase"] = "strategist"
                status["phase_detail"] = (
                    "Strategist choosing 5 topics, gift theme, and CTA keyword..."
                )

                result = await orch.run(context)
                await bg_db.commit()

                ctx = result.get("context", {})
                weekly_plan = ctx.get("weekly_plan", {})
                trend_brief = ctx.get("trend_brief", {})

                if not weekly_plan or not weekly_plan.get("days"):
                    status["status"] = "failed"
                    status["phase"] = "failed"
                    status["error"] = "Weekly planner did not produce a valid plan"
                    await _save_plan_to_db(plan_id, status)
                    return

                # Create/update calendar entries + slot options
                week_plan_uuid = uuid.uuid4()
                guide_opts_raw = weekly_plan.get("guide_options", [])
                # Backward compat: derive gift_theme from guide_options[0]
                first_guide = guide_opts_raw[0] if guide_opts_raw else {}
                gift_theme = first_guide.get("title", weekly_plan.get("gift_theme", ""))
                gift_sections = first_guide.get("sections", weekly_plan.get("gift_sections", []))

                for day_plan in weekly_plan.get("days", []):
                    day_num = day_plan.get("day_of_week", 0)
                    entry_date = request.week_start + timedelta(days=day_num)

                    existing = await bg_db.execute(
                        select(ContentCalendarEntry).where(
                            ContentCalendarEntry.date == entry_date
                        )
                    )
                    entry = existing.scalar_one_or_none()

                    # Handle new multi-option format or old flat format
                    options = day_plan.get("options", [])
                    if not options and day_plan.get("topic"):
                        options = [day_plan]  # Backward compat: single option

                    # Enforce content_format on the designated video days, even
                    # if the LLM forgot to set it. Other days default to "text".
                    is_video_day = day_num in set(request.resolved_video_days())
                    desired_format = "walking_video" if is_video_day else "text"
                    for opt in options:
                        if is_video_day or not opt.get("content_format"):
                            opt["content_format"] = desired_format

                    # Primary option (index 0) is the default selection
                    primary = options[0] if options else day_plan
                    story_brief = primary
                    enriched_context = {
                        **story_brief,
                        "_weekly": {
                            "weekly_theme": weekly_plan.get("weekly_theme", ""),
                            "gift_theme": gift_theme,
                            "gift_sections": gift_sections,
                            "cta_keyword": weekly_plan.get("cta_keyword", ""),
                        },
                    }
                    # Mirror content_format at the top level of plan_context so the
                    # dashboard can read it without digging into nested options.
                    enriched_context["content_format"] = primary.get("content_format") or desired_format

                    if entry:
                        entry.topic = story_brief.get("topic", entry.topic)
                        entry.plan_context = enriched_context
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
                            plan_context=enriched_context,
                            weekly_plan_id=week_plan_uuid,
                        )
                        bg_db.add(entry)

                    await bg_db.flush()  # Get entry.id for slot options

                    # Save slot options for this day
                    # First, delete any old options for this entry
                    old_opts = await bg_db.execute(
                        select(SlotOption).where(
                            SlotOption.calendar_entry_id == entry.id
                        )
                    )
                    for old in old_opts.scalars().all():
                        await bg_db.delete(old)

                    for idx, opt in enumerate(options):
                        slot = SlotOption(
                            calendar_entry_id=entry.id,
                            option_index=idx,
                            topic=opt.get("topic", ""),
                            angle_type=opt.get("angle_type", day_plan.get("angle_type", "")),
                            plan_context=opt,
                            is_selected=(idx == 0),
                        )
                        bg_db.add(slot)

                # Save guide options
                for gidx, gopt in enumerate(guide_opts_raw):
                    bg_db.add(GuideOption(
                        weekly_plan_id=week_plan_uuid,
                        option_index=gidx,
                        title=gopt.get("title", ""),
                        subtitle=gopt.get("subtitle"),
                        sections=gopt.get("sections"),
                        rationale=gopt.get("rationale"),
                        is_selected=(gidx == 0),
                    ))

                await bg_db.commit()

                # Trim trend_brief for response
                trend_summary = []
                for t in trend_brief.get("trends", [])[:10]:
                    trend_summary.append(
                        {
                            "headline": t.get("headline", ""),
                            "relevance_score": t.get("relevance_score", 0),
                            "source_url": t.get("source_url", ""),
                            "angle_suggestions": t.get(
                                "angle_suggestions", t.get("angles", [])
                            ),
                        }
                    )

                status["status"] = "completed"
                status["phase"] = "completed"
                status["phase_detail"] = "Plan ready for review"
                status["weekly_plan"] = weekly_plan
                status["weekly_plan_id"] = str(week_plan_uuid)
                status["trend_summary"] = trend_summary
                status["completed_at"] = datetime.utcnow().isoformat()

                # Persist completed plan to DB
                await _save_plan_to_db(plan_id, status)

            except Exception as e:
                logger.exception("plan_week_deep.error", plan_id=plan_id)
                status["status"] = "failed"
                status["phase"] = "failed"
                status["error"] = str(e)
                await _save_plan_to_db(plan_id, status)

    asyncio.create_task(_run_deep_plan())

    return {
        "plan_id": plan_id,
        "status": "started",
        "status_url": f"/api/v1/calendar/plan-week-deep/{plan_id}/status",
    }


@router.get("/plan-week-deep/{plan_id}/status")
async def get_deep_plan_status(plan_id: str) -> dict[str, Any]:
    """Get the status of a deep planning run."""
    plan = await _get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post("/plan-week-deep/{plan_id}/approve")
async def approve_deep_plan(
    plan_id: str,
    request: PlanApproveRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve (and optionally edit) the deep plan. Updates calendar entries."""
    plan_status = await _get_plan(plan_id)
    if not plan_status:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan_status["status"] != "completed":
        raise HTTPException(status_code=400, detail="Plan is not ready for approval")

    week_start_str = plan_status.get("week_start")
    if not week_start_str:
        raise HTTPException(status_code=400, detail="Plan missing week_start")

    week_start = date.fromisoformat(week_start_str)
    for day_plan in request.days:
        day_num = day_plan.get("day_of_week", 0)
        entry_date = week_start + timedelta(days=day_num)

        result = await db.execute(
            select(ContentCalendarEntry).where(ContentCalendarEntry.date == entry_date)
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.topic = day_plan.get("topic", entry.topic)
            entry.plan_context = day_plan
            entry.status = "approved"
            gift = (
                request.gift_theme
                if isinstance(request.gift_theme, str)
                else request.gift_theme.get("title", "")
            )
            entry.operator_notes = (
                f"Weekly theme: {request.weekly_theme} | CTA: {request.cta_keyword} | Gift: {gift}"
            )

    await db.flush()

    # Update plan status
    plan_status["approved"] = True
    plan_status["status"] = "approved"
    plan_status["approved_plan"] = {
        "weekly_theme": request.weekly_theme,
        "gift_theme": request.gift_theme,
        "cta_keyword": request.cta_keyword,
        "days": request.days,
    }
    _deep_plans_cache[plan_id] = plan_status
    await _save_plan_to_db(plan_id, plan_status)

    return {
        "plan_id": plan_id,
        "status": "approved",
        "message": "Plan approved and calendar entries updated",
    }


@router.post("/ai-revise-field")
async def ai_revise_field(
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Use AI to revise a single plan/package field based on operator feedback."""
    field_name = payload.get("field_name", "")
    current_value = payload.get("current_value", "")
    feedback = payload.get("feedback", "")
    context = payload.get("context", {})

    if not feedback.strip():
        raise HTTPException(status_code=400, detail="Feedback text is required")

    import anthropic

    from tce.services.cost_tracker import CostTracker

    s = Settings()
    api_key = s.anthropic_api_key
    if hasattr(api_key, "get_secret_value"):
        api_key = api_key.get_secret_value()
    client = anthropic.AsyncAnthropic(api_key=api_key)

    # Detect if this is a full post field (needs more tokens + humanization)
    is_post_field = any(kw in field_name.lower() for kw in ("_post", "post_", "caption", "body", "content"))

    base_rules = (
        "You are a content strategist for a B2B social media team. "
        "The operator wants you to revise a specific field in their weekly content plan. "
        "Apply the feedback precisely. Return ONLY the revised text - no explanation, no quotes, no markdown. "
        "NEVER use emdashes or double dashes. Use a single dash (-) instead."
    )

    if is_post_field:
        system_prompt = (
            base_rules + " "
            "Write in a warm, conversational, human tone - not robotic or corporate. "
            "Vary sentence length. Use contractions naturally. "
            "The revised post MUST be at least as long as the original - do NOT truncate or shorten it. "
            "Preserve the full structure and all key points from the original."
        )
        model = s.default_model  # Sonnet
        max_tokens = 2048
    else:
        system_prompt = base_rules
        model = s.haiku_model
        max_tokens = 512

    context_str = ""
    if context.get("weekly_theme"):
        context_str += f"Weekly theme: {context['weekly_theme']}\n"
    if context.get("day_topic"):
        context_str += f"Day topic: {context['day_topic']}\n"

    user_msg = (
        f"Field: {field_name}\n"
        f"Current value: {current_value}\n"
        f"{context_str}"
        f"\nFeedback from operator: {feedback}\n\n"
        f"Rewrite this field applying the feedback. Return ONLY the revised text."
    )

    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.5,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    revised = resp.content[0].text.strip()

    # Record cost
    tracker = CostTracker(db)
    await tracker.record(
        run_id=uuid.uuid4(),
        agent_name="field_reviser",
        model_used=model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
    await db.commit()

    return {"revised": revised, "model": model}


# ---------------------------------------------------------------------------
# Slot Options - multiple topic options per day slot (Phase 1)
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/options")
async def list_slot_options(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all options for a calendar day slot."""
    result = await db.execute(
        select(SlotOption)
        .where(SlotOption.calendar_entry_id == entry_id)
        .order_by(SlotOption.option_index)
    )
    options = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "option_index": o.option_index,
            "topic": o.topic,
            "angle_type": o.angle_type,
            "plan_context": o.plan_context,
            "is_selected": o.is_selected,
            "post_package_id": str(o.post_package_id) if o.post_package_id else None,
        }
        for o in options
    ]


@router.post("/{entry_id}/options/{option_idx}/select")
async def select_slot_option(
    entry_id: uuid.UUID,
    option_idx: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Select an option for a day slot. Updates the parent calendar entry."""
    # Deselect all options for this entry
    result = await db.execute(
        select(SlotOption).where(SlotOption.calendar_entry_id == entry_id)
    )
    options = result.scalars().all()

    selected = None
    for o in options:
        o.is_selected = (o.option_index == option_idx)
        if o.is_selected:
            selected = o

    if not selected:
        raise HTTPException(status_code=404, detail=f"Option {option_idx} not found")

    # Update the parent calendar entry with the selected option's data
    entry = await db.get(ContentCalendarEntry, entry_id)
    if entry:
        entry.topic = selected.topic
        entry.angle_type = selected.angle_type
        # Merge selected option's plan_context into entry
        if selected.plan_context:
            enriched = {
                **selected.plan_context,
                "_weekly": entry.plan_context.get("_weekly", {}) if entry.plan_context else {},
            }
            entry.plan_context = enriched

    await db.commit()
    return {"status": "selected", "option_index": option_idx, "topic": selected.topic}


@router.post("/{entry_id}/regenerate-alternatives")
async def regenerate_alternatives(
    entry_id: uuid.UUID,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate N fresh topic alternatives for a calendar day slot.

    Replaces the existing non-selected, non-packaged SlotOption rows so the
    modal always shows a fresh batch. The selected option and any options
    with a generated post_package_id are preserved (those represent work
    the operator has invested in).

    All prior topics on this slot are passed to the LLM as an exclusion
    list so each click yields fresh ideas. After 3 regen cycles with no
    fresh research, the next regen auto-runs trend_scout to seed new
    angles ("when out of topics, go back to research").
    """
    payload = payload or {}
    count = max(1, min(int(payload.get("count", 3)), 5))
    use_fresh_research = bool(payload.get("use_fresh_research", False))

    entry = await db.get(ContentCalendarEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Calendar entry not found")

    # Collect ALL prior topics on this slot (selected + history) so the LLM
    # never repeats. This is the key to "give me new ones until I'm happy".
    result = await db.execute(
        select(SlotOption)
        .where(SlotOption.calendar_entry_id == entry_id)
        .order_by(SlotOption.option_index)
    )
    existing = list(result.scalars().all())
    seen_topics = [o.topic for o in existing if o.topic]
    if entry.topic and entry.topic not in seen_topics:
        seen_topics.append(entry.topic)

    pc = entry.plan_context or {}
    weekly = pc.get("_weekly", {}) if isinstance(pc.get("_weekly"), dict) else {}
    angle = entry.angle_type or pc.get("angle_type", "")
    angle_desc = ANGLE_DESCRIPTIONS.get(angle, angle or "general AI/business commentary")
    weekly_theme = weekly.get("weekly_theme", "")
    cta = weekly.get("cta_keyword", "")
    gift_theme = weekly.get("gift_theme") or pc.get("gift_theme") or ""
    if isinstance(gift_theme, dict):
        gift_theme = gift_theme.get("title", "")
    connection_to_gift = pc.get("connection_to_gift", "")

    # Track regen cycles. Auto-trigger fresh research after 3 cycles since
    # the last research run (or if the operator explicitly asks).
    cycles = int(pc.get("alt_regen_cycles", 0))
    last_research_at = int(pc.get("alt_research_at_cycle", -1))
    auto_research = (cycles - last_research_at) >= 3
    do_research = use_fresh_research or auto_research or last_research_at < 0

    fresh_trends: list[dict[str, Any]] = []
    if do_research:
        try:
            from tce.agents.cost_tracker import CostTracker
            from tce.agents.registry import get_agent_class

            scout_cls = get_agent_class("trend_scout")
            scout = scout_cls(
                db=db,
                settings=settings,
                cost_tracker=CostTracker(db),
                prompt_manager=None,
                run_id=uuid.uuid4(),
                progress_log=None,
            )
            scout_ctx = {"scan_type": "daily", "focus_areas": ["AI", "business automation"]}
            scout_result = await scout._execute(scout_ctx)
            fresh_trends = (scout_result.get("trend_brief") or {}).get("trends", [])[:10]
            logger.info(
                "calendar.alt_research_done",
                entry_id=str(entry_id),
                trends=len(fresh_trends),
            )
        except Exception as exc:
            logger.warning("calendar.alt_research_failed", error=str(exc))
            fresh_trends = []

    # Pull strategy + portfolio so alternatives match the same standards
    # as the planner's output (named repos, specific model versions, etc.)
    from tce.services.strategy_loader import load_portfolio, load_strategy
    strategy_text = load_strategy()
    portfolio_text = load_portfolio()

    import anthropic

    settings_local = Settings()
    client = anthropic.AsyncAnthropic(api_key=settings_local.anthropic_api_key)

    seen_block = (
        "\n".join(f"- {t}" for t in seen_topics) if seen_topics else "(none yet)"
    )
    trends_block = (
        "\n\nFRESH TREND BRIEF (from team-wide research, last 14 days):\n"
        + json.dumps(fresh_trends, indent=2)
        if fresh_trends
        else ""
    )
    weekly_block = f"\nWEEKLY THEME: {weekly_theme}" if weekly_theme else ""
    gift_block = f"\nGUIDE/GIFT: {gift_theme}" if gift_theme else ""
    cta_block = f"\nCTA KEYWORD: {cta}" if cta else ""
    connection_block = (
        f"\nGUIDE CONNECTION (each topic must tie back to this): {connection_to_gift}"
        if connection_to_gift
        else ""
    )
    portfolio_block = (
        "\n\nREPO PORTFOLIO (case-study material, reference by name when fitting):\n"
        + portfolio_text
        if portfolio_text
        else ""
    )
    strategy_block = (
        "\n\nBUSINESS STRATEGY (alternatives must pass the same filter):\n"
        + strategy_text[:6000]
        if strategy_text
        else ""
    )

    prompt = (
        f"You are generating {count} FRESH alternative topic options for a content calendar day.\n"
        f"\nANGLE: {angle} - {angle_desc}"
        f"{weekly_block}{gift_block}{cta_block}{connection_block}"
        f"{strategy_block}"
        f"{portfolio_block}"
        f"{trends_block}\n"
        f"\nDO NOT REPEAT ANY OF THESE TOPICS (operator has already seen them):\n{seen_block}\n"
        f"\nEach option must be:\n"
        f"- Specific (real companies, tools, model versions, numbers - cite Sonnet 4.6 / Opus 4.7 / GPT-5 / Gemini 2.5 by name when relevant)\n"
        f"- Scroll-stopping (the viewer knows the stake in 5 seconds)\n"
        f"- Distinct from the others (don't generate {count} variations of the same idea)\n"
        f"- Aligned with the angle and weekly theme\n"
        f"- Where natural, tie back to a named Kivi Media repo as case-study proof (don't force it)\n"
        f"\nOutput ONLY a JSON array of {count} objects, no markdown, no commentary. Each object:\n"
        '{"topic": "1 sentence", "thesis": "1-2 sentences plain language", '
        '"audience": "specific reader (e.g. agency owners $10-50K/mo)", '
        '"desired_belief_shift": "FROM x TO y", '
        '"evidence_requirements": ["claim to verify"], '
        '"visual_job": "cinematic_symbolic|proof_diagram|emotional_alternate", '
        '"connection_to_gift": "how it ties to the guide", '
        '"platform_notes": ""}'
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2400,
            temperature=0.85,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.exception("calendar.alt_llm_failed")
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        new_options = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("calendar.alt_parse_failed", text=text[:300])
        raise HTTPException(
            status_code=502, detail=f"LLM returned malformed JSON: {exc}"
        ) from exc

    if not isinstance(new_options, list) or not new_options:
        raise HTTPException(status_code=502, detail="LLM returned no options")

    # Delete prior NON-SELECTED, NON-PACKAGED rows to keep the modal clean.
    # Selected option stays. Options with a generated post_package_id stay
    # (preserves work the operator already invested in).
    deleted = 0
    for o in existing:
        if o.is_selected or o.post_package_id:
            continue
        await db.delete(o)
        deleted += 1

    next_idx = max((o.option_index for o in existing), default=-1) + 1
    created_topics: list[str] = []
    for i, opt in enumerate(new_options[:count]):
        if not isinstance(opt, dict) or not opt.get("topic"):
            continue
        slot = SlotOption(
            calendar_entry_id=entry_id,
            option_index=next_idx + i,
            topic=opt.get("topic", ""),
            angle_type=angle or "",
            plan_context=opt,
            is_selected=False,
        )
        db.add(slot)
        created_topics.append(opt.get("topic", ""))

    # Update regen-cycle counters on the parent entry so the next call
    # knows how many cycles since the last research run.
    new_pc = dict(pc)
    new_pc["alt_regen_cycles"] = cycles + 1
    if do_research:
        new_pc["alt_research_at_cycle"] = cycles + 1
    entry.plan_context = new_pc

    await db.commit()
    logger.info(
        "calendar.alternatives_regenerated",
        entry_id=str(entry_id),
        created=len(created_topics),
        deleted=deleted,
        used_research=do_research,
        cycle=cycles + 1,
    )
    return {
        "created": len(created_topics),
        "deleted": deleted,
        "used_research": do_research,
        "cycle": cycles + 1,
    }


@router.post("/{entry_id}/options/{option_idx}/move")
async def move_slot_option(
    entry_id: uuid.UUID,
    option_idx: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Move a slot option to a different calendar entry (cross-day/cross-week drag)."""
    target_entry_id = payload.get("target_entry_id")
    if not target_entry_id:
        raise HTTPException(status_code=400, detail="target_entry_id required")

    target_entry_id = uuid.UUID(target_entry_id)

    # Find the source option
    result = await db.execute(
        select(SlotOption).where(
            SlotOption.calendar_entry_id == entry_id,
            SlotOption.option_index == option_idx,
        )
    )
    option = result.scalar_one_or_none()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    # Verify target entry exists
    target_entry = await db.get(ContentCalendarEntry, target_entry_id)
    if not target_entry:
        raise HTTPException(status_code=404, detail="Target entry not found")

    # Get current max option_index on target
    target_opts = await db.execute(
        select(SlotOption)
        .where(SlotOption.calendar_entry_id == target_entry_id)
        .order_by(SlotOption.option_index.desc())
    )
    max_idx = 0
    for to in target_opts.scalars().all():
        max_idx = max(max_idx, to.option_index + 1)

    # Move the option
    option.calendar_entry_id = target_entry_id
    option.option_index = max_idx
    option.is_selected = False

    await db.commit()
    return {
        "status": "moved",
        "from_entry": str(entry_id),
        "to_entry": str(target_entry_id),
        "new_index": max_idx,
    }


# ---------------------------------------------------------------------------
# Guide Options - multiple freebie ideas per week (Phase 4)
# ---------------------------------------------------------------------------


@router.get("/guide-options/{weekly_plan_id}")
async def list_guide_options(
    weekly_plan_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List guide options for a weekly plan."""
    plan_uuid = uuid.UUID(weekly_plan_id)
    result = await db.execute(
        select(GuideOption)
        .where(GuideOption.weekly_plan_id == plan_uuid)
        .order_by(GuideOption.option_index)
    )
    return [
        {
            "id": str(g.id),
            "option_index": g.option_index,
            "title": g.title,
            "subtitle": g.subtitle,
            "sections": g.sections,
            "rationale": g.rationale,
            "is_selected": g.is_selected,
            "weekly_guide_id": str(g.weekly_guide_id) if g.weekly_guide_id else None,
        }
        for g in result.scalars().all()
    ]


@router.post("/guide-options/{option_id}/select")
async def select_guide_option(
    option_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Select a guide option. Deselects all others for the same weekly plan."""
    option = await db.get(GuideOption, option_id)
    if not option:
        raise HTTPException(status_code=404, detail="Guide option not found")

    # Deselect siblings
    siblings = await db.execute(
        select(GuideOption).where(GuideOption.weekly_plan_id == option.weekly_plan_id)
    )
    for sib in siblings.scalars().all():
        sib.is_selected = (sib.id == option_id)

    await db.commit()
    return {"status": "selected", "title": option.title}
