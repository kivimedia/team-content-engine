"""Content calendar endpoints (PRD Section 43.3)."""

import uuid
from datetime import date, timedelta

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
    return entries


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
