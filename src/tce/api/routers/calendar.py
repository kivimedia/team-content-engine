"""Content calendar endpoints (PRD Section 43.3)."""

import json
import uuid
from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.models.content_calendar import ContentCalendarEntry
from tce.schemas.content_calendar import (
    ContentCalendarRead,
    ContentCalendarUpdate,
    PlanWeekRequest,
)
from tce.settings import Settings

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
