"""Monthly planning endpoints - plan 4 weeks at once."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import async_session, get_db
from tce.models.content_calendar import ContentCalendarEntry
from tce.models.guide_option import GuideOption
from tce.models.monthly_plan import MonthlyPlan
from tce.models.slot_option import SlotOption
from tce.models.weekly_plan import WeeklyPlan
from tce.settings import settings

logger = structlog.get_logger()

router = APIRouter(prefix="/monthly", tags=["monthly"])

# In-memory cache for active monthly plans
_monthly_cache: dict[str, dict[str, Any]] = {}

DEFAULT_CADENCE = {
    0: "big_shift_explainer",
    1: "tactical_workflow_guide",
    2: "contrarian_diagnosis",
    3: "case_study_build_story",
    4: "second_order_implication",
}


class MonthPlanRequest(BaseModel):
    month_start: date  # Should be a Monday
    monthly_theme: str | None = None
    sensitive_period: bool = False
    seasonal_context: str | None = None
    niche: str = "general"  # "coaching" for Super Coaching niche


@router.post("/plan")
async def plan_month(
    request: MonthPlanRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start 4-week planning. Runs trend_scout once, then weekly_planner 4x."""
    plan_id = str(uuid.uuid4())

    # Create MonthlyPlan record
    mp = MonthlyPlan(
        month_start=request.month_start,
        status="planning",
        plan_data={
            "monthly_theme": request.monthly_theme,
            "sensitive_period": request.sensitive_period,
            "seasonal_context": request.seasonal_context,
        },
    )
    db.add(mp)
    await db.commit()
    mp_id = mp.id

    status: dict[str, Any] = {
        "plan_id": plan_id,
        "monthly_plan_id": str(mp_id),
        "status": "planning",
        "phase": "starting",
        "phase_detail": "Starting 4-week planning...",
        "weeks": [],
        "started_at": datetime.utcnow().isoformat(),
    }
    _monthly_cache[plan_id] = status

    async def _run_monthly_plan() -> None:
        try:
            from tce.agents.registry import get_agent_class
            from tce.models.creator_profile import CreatorProfile
            from tce.models.founder_voice_profile import FounderVoiceProfile
            from tce.orchestrator.engine import PipelineOrchestrator
            from tce.orchestrator.step import PipelineStep
            from tce.services.cost_tracker import CostTracker
            from tce.services.prompt_manager import PromptManager

            async with async_session() as bg_db:
                # Load voice context (shared across all 4 weeks)
                fv_result = await bg_db.execute(select(FounderVoiceProfile).limit(1))
                fv = fv_result.scalar_one_or_none()
                founder_voice = None
                if fv:
                    founder_voice = {
                        "recurring_themes": fv.recurring_themes or [],
                        "values_and_beliefs": fv.values_and_beliefs or [],
                        "taboos": fv.taboos or [],
                        "tone_range": fv.tone_range,
                        "humor_type": fv.humor_type,
                        "metaphor_families": fv.metaphor_families or [],
                    }

                cr_result = await bg_db.execute(select(CreatorProfile))
                creators = cr_result.scalars().all()
                creator_profiles = [
                    {
                        "name": c.creator_name,
                        "style": c.style_notes,
                        "voice_axes": c.voice_axes,
                        "top_patterns": c.top_patterns or [],
                        "allowed_influence_weight": c.allowed_influence_weight,
                    }
                    for c in creators
                ]

                # Step 1: Run trend_scout ONCE for the whole month
                status["phase"] = "trend_scanning"
                status["phase_detail"] = "Scanning trends for the month..."

                trend_scout_cls = get_agent_class("trend_scout")
                run_id = uuid.uuid4()
                cost_tracker = CostTracker(bg_db)
                prompt_manager = PromptManager(bg_db)

                trend_scout = trend_scout_cls(
                    db=bg_db,
                    settings=settings,
                    cost_tracker=cost_tracker,
                    prompt_manager=prompt_manager,
                    run_id=run_id,
                )
                scout_ctx = {
                    "scan_type": "weekly",
                    "focus_areas": ["AI", "technology", "business automation"],
                    "niche": request.niche,
                }
                scout_result = await trend_scout._execute(scout_ctx)
                shared_trend_brief = scout_result.get("trend_brief", {})
                await bg_db.commit()

                status["phase_detail"] = f"Found {len(shared_trend_brief.get('trends', []))} trends"

                # Load historical topics from past posts to avoid repetition
                from tce.models.post_package import PostPackage
                hist_result = await bg_db.execute(
                    select(PostPackage.topic)
                    .where(PostPackage.topic.isnot(None))
                    .order_by(PostPackage.created_at.desc())
                    .limit(50)
                )
                historical_topics = [r[0] for r in hist_result.all() if r[0]]

                # Also load recent calendar entry topics
                from datetime import datetime as dt_cls
                thirty_days_ago = dt_cls.utcnow().date() - timedelta(days=30)
                cal_result = await bg_db.execute(
                    select(ContentCalendarEntry.topic)
                    .where(ContentCalendarEntry.topic.isnot(None))
                    .where(ContentCalendarEntry.date >= thirty_days_ago)
                )
                for r in cal_result.all():
                    if r[0] and r[0] not in historical_topics:
                        historical_topics.append(r[0])

                status["phase_detail"] = f"Found {len(shared_trend_brief.get('trends', []))} trends, {len(historical_topics)} past topics to avoid"

                # Step 2: Run weekly_planner 4 times
                weekly_plan_ids = []
                all_prior_topics: list[str] = list(historical_topics)

                for week_idx in range(4):
                    week_start = request.month_start + timedelta(weeks=week_idx)
                    status["phase"] = f"planning_week_{week_idx + 1}"
                    status["phase_detail"] = f"Planning week {week_idx + 1}/4 ({week_start.strftime('%b %d')})..."

                    weekly_planner_cls = get_agent_class("weekly_planner")
                    week_run_id = uuid.uuid4()
                    planner = weekly_planner_cls(
                        db=bg_db,
                        settings=settings,
                        cost_tracker=cost_tracker,
                        prompt_manager=prompt_manager,
                        run_id=week_run_id,
                    )

                    # Supplement the shared brief with fresh searches per week
                    # so later weeks get different angles, not just the same pool
                    week_brief = dict(shared_trend_brief)
                    week_trends = list(shared_trend_brief.get("trends", []))

                    if week_idx > 0:
                        # Run a few supplemental searches for variety
                        from tce.services.web_search import WebSearchService
                        supp_search = WebSearchService()
                        if supp_search.api_key:
                            variety_queries = [
                                f"week {week_idx + 1} AI business news",
                                "startup founder story this week",
                                "productivity hack tool launch",
                                "digital marketing trend",
                            ]
                            supp_results = []
                            for vq in variety_queries[week_idx - 1:week_idx + 1]:
                                sr = await supp_search.search_news(vq, count=5)
                                supp_results.extend(sr)
                            if supp_results:
                                # Ask trend scout to evaluate supplemental results
                                supp_scout = trend_scout_cls(
                                    db=bg_db, settings=settings,
                                    cost_tracker=cost_tracker,
                                    prompt_manager=prompt_manager,
                                    run_id=uuid.uuid4(),
                                )
                                supp_ctx = {
                                    "scan_type": "supplemental",
                                    "focus_areas": ["business", "creator economy", "SaaS"],
                                }
                                supp_result = await supp_scout._execute(supp_ctx)
                                supp_trends = supp_result.get("trend_brief", {}).get("trends", [])
                                # Merge new trends, avoiding duplicates by headline
                                existing_headlines = {t.get("headline", "") for t in week_trends}
                                for st in supp_trends:
                                    if st.get("headline", "") not in existing_headlines:
                                        week_trends.append(st)
                                await bg_db.commit()

                    week_brief["trends"] = week_trends

                    # Skip internal trend_scout by providing trend_brief directly
                    week_context: dict[str, Any] = {
                        "trend_brief": week_brief,
                        "_skip_trend_scout": True,
                        "founder_voice": founder_voice,
                        "creator_profiles": creator_profiles,
                        "sensitive_period": request.sensitive_period,
                        "recent_posts": [{"topic": t} for t in all_prior_topics],
                        "niche": request.niche,
                    }
                    if request.monthly_theme:
                        week_context["operator_overrides"] = {
                            "monthly_theme": request.monthly_theme,
                        }
                    if request.seasonal_context:
                        week_context["humanitarian_context"] = request.seasonal_context

                    planner_result = await planner._execute(week_context)
                    await bg_db.commit()

                    weekly_plan = planner_result.get("weekly_plan", {})

                    # Save WeeklyPlan record
                    wp = WeeklyPlan(
                        status="completed",
                        plan_data=weekly_plan,
                        week_start=week_start,
                        run_id=week_run_id,
                    )
                    bg_db.add(wp)
                    await bg_db.flush()
                    weekly_plan_ids.append(str(wp.id))

                    # Create calendar entries + slot options
                    guide_opts_raw = weekly_plan.get("guide_options", [])
                    first_guide = guide_opts_raw[0] if guide_opts_raw else {}
                    gift_theme = first_guide.get("title", weekly_plan.get("gift_theme", ""))
                    gift_sections = first_guide.get("sections", weekly_plan.get("gift_sections", []))

                    for day_plan in weekly_plan.get("days", []):
                        day_num = day_plan.get("day_of_week", 0)
                        entry_date = week_start + timedelta(days=day_num)

                        existing = await bg_db.execute(
                            select(ContentCalendarEntry).where(
                                ContentCalendarEntry.date == entry_date
                            )
                        )
                        entry = existing.scalar_one_or_none()

                        options = day_plan.get("options", [])
                        if not options and day_plan.get("topic"):
                            options = [day_plan]

                        primary = options[0] if options else day_plan
                        enriched_context = {
                            **primary,
                            "_weekly": {
                                "weekly_theme": weekly_plan.get("weekly_theme", ""),
                                "gift_theme": gift_theme,
                                "gift_sections": gift_sections,
                                "cta_keyword": weekly_plan.get("cta_keyword", ""),
                            },
                        }

                        if entry:
                            entry.topic = primary.get("topic", entry.topic)
                            entry.plan_context = enriched_context
                            entry.weekly_plan_id = wp.id
                            entry.status = "planned"
                        else:
                            angle = DEFAULT_CADENCE.get(day_num, "big_shift_explainer")
                            entry = ContentCalendarEntry(
                                date=entry_date,
                                day_of_week=day_num,
                                angle_type=primary.get("angle_type", angle),
                                topic=primary.get("topic"),
                                status="planned",
                                plan_context=enriched_context,
                                weekly_plan_id=wp.id,
                            )
                            bg_db.add(entry)

                        await bg_db.flush()

                        # Save slot options
                        old_opts = await bg_db.execute(
                            select(SlotOption).where(SlotOption.calendar_entry_id == entry.id)
                        )
                        for old in old_opts.scalars().all():
                            await bg_db.delete(old)

                        for idx, opt in enumerate(options):
                            bg_db.add(SlotOption(
                                calendar_entry_id=entry.id,
                                option_index=idx,
                                topic=opt.get("topic", ""),
                                angle_type=opt.get("angle_type", day_plan.get("angle_type", "")),
                                plan_context=opt,
                                is_selected=(idx == 0),
                            ))

                        # Track topics to avoid repetition in later weeks
                        for opt in options:
                            if opt.get("topic"):
                                all_prior_topics.append(opt["topic"])

                    # Save guide options
                    for gidx, gopt in enumerate(guide_opts_raw):
                        bg_db.add(GuideOption(
                            weekly_plan_id=wp.id,
                            option_index=gidx,
                            title=gopt.get("title", ""),
                            subtitle=gopt.get("subtitle"),
                            sections=gopt.get("sections"),
                            rationale=gopt.get("rationale"),
                            is_selected=(gidx == 0),
                        ))

                    await bg_db.commit()

                    week_summary = {
                        "week_idx": week_idx,
                        "week_start": str(week_start),
                        "weekly_plan_id": str(wp.id),
                        "weekly_theme": weekly_plan.get("weekly_theme", ""),
                        "days": len(weekly_plan.get("days", [])),
                        "guide_options": len(guide_opts_raw),
                    }
                    status.setdefault("weeks", []).append(week_summary)

                # Update MonthlyPlan record
                mp_record = await bg_db.get(MonthlyPlan, mp_id)
                if mp_record:
                    mp_record.status = "review"
                    mp_record.weekly_plan_ids = weekly_plan_ids
                    mp_record.plan_data = {
                        **(mp_record.plan_data or {}),
                        "trend_count": len(shared_trend_brief.get("trends", [])),
                    }
                await bg_db.commit()

                status["status"] = "completed"
                status["phase"] = "completed"
                status["phase_detail"] = "4-week plan ready for review"
                status["completed_at"] = datetime.utcnow().isoformat()

        except Exception as e:
            logger.exception("monthly_plan.error", plan_id=plan_id)
            status["status"] = "failed"
            status["phase"] = "failed"
            status["error"] = str(e)

    asyncio.create_task(_run_monthly_plan())

    return {
        "plan_id": plan_id,
        "monthly_plan_id": str(mp_id),
        "status": "started",
        "status_url": f"/api/v1/monthly/{plan_id}/status",
    }


@router.get("/{plan_id}/status")
async def get_monthly_plan_status(plan_id: str) -> dict[str, Any]:
    """Poll monthly planning progress."""
    status = _monthly_cache.get(plan_id)
    if not status:
        raise HTTPException(status_code=404, detail="Monthly plan not found")
    return status


@router.get("/{plan_id}")
async def get_monthly_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get full monthly plan with all 4 weeks, options, and guide options."""
    status = _monthly_cache.get(plan_id)
    if not status:
        raise HTTPException(status_code=404, detail="Monthly plan not found")

    mp_id = status.get("monthly_plan_id")
    if not mp_id:
        return status

    mp = await db.get(MonthlyPlan, uuid.UUID(mp_id))
    if not mp:
        return status

    weeks_data = []
    for wp_id_str in (mp.weekly_plan_ids or []):
        wp = await db.get(WeeklyPlan, uuid.UUID(wp_id_str))
        if not wp:
            continue

        # Load calendar entries for this week
        entries_result = await db.execute(
            select(ContentCalendarEntry)
            .where(ContentCalendarEntry.weekly_plan_id == wp.id)
            .order_by(ContentCalendarEntry.date)
        )
        entries = entries_result.scalars().all()

        days = []
        for entry in entries:
            # Load slot options
            opts_result = await db.execute(
                select(SlotOption)
                .where(SlotOption.calendar_entry_id == entry.id)
                .order_by(SlotOption.option_index)
            )
            slot_opts = [
                {
                    "id": str(o.id),
                    "option_index": o.option_index,
                    "topic": o.topic,
                    "angle_type": o.angle_type,
                    "plan_context": o.plan_context,
                    "is_selected": o.is_selected,
                }
                for o in opts_result.scalars().all()
            ]

            days.append({
                "entry_id": str(entry.id),
                "date": str(entry.date),
                "day_of_week": entry.day_of_week,
                "topic": entry.topic,
                "angle_type": entry.angle_type,
                "status": entry.status,
                "options": slot_opts,
            })

        # Load guide options
        guide_result = await db.execute(
            select(GuideOption)
            .where(GuideOption.weekly_plan_id == wp.id)
            .order_by(GuideOption.option_index)
        )
        guides = [
            {
                "id": str(g.id),
                "option_index": g.option_index,
                "title": g.title,
                "subtitle": g.subtitle,
                "sections": g.sections,
                "rationale": g.rationale,
                "is_selected": g.is_selected,
            }
            for g in guide_result.scalars().all()
        ]

        plan_data = wp.plan_data or {}
        weeks_data.append({
            "weekly_plan_id": str(wp.id),
            "week_start": str(wp.week_start),
            "weekly_theme": plan_data.get("weekly_theme", ""),
            "cta_keyword": plan_data.get("cta_keyword", ""),
            "days": days,
            "guide_options": guides,
        })

    return {
        "plan_id": plan_id,
        "monthly_plan_id": str(mp.id),
        "month_start": str(mp.month_start),
        "status": mp.status,
        "plan_data": mp.plan_data,
        "weeks": weeks_data,
    }


@router.post("/{plan_id}/approve")
async def approve_monthly_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve the monthly plan. Sets all calendar entries to approved."""
    status = _monthly_cache.get(plan_id)
    if not status:
        raise HTTPException(status_code=404, detail="Monthly plan not found")

    mp_id = status.get("monthly_plan_id")
    if not mp_id:
        raise HTTPException(status_code=400, detail="No monthly plan record")

    mp = await db.get(MonthlyPlan, uuid.UUID(mp_id))
    if not mp:
        raise HTTPException(status_code=404, detail="Monthly plan record not found")

    # Update all calendar entries to approved
    for wp_id_str in (mp.weekly_plan_ids or []):
        entries_result = await db.execute(
            select(ContentCalendarEntry).where(
                ContentCalendarEntry.weekly_plan_id == uuid.UUID(wp_id_str)
            )
        )
        for entry in entries_result.scalars().all():
            entry.status = "approved"

    mp.status = "approved"
    await db.commit()

    return {
        "plan_id": plan_id,
        "status": "approved",
        "message": "All 4 weeks approved",
    }
