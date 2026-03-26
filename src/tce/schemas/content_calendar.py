"""Schemas for ContentCalendarEntry."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ContentCalendarCreate(BaseModel):
    date: date
    day_of_week: int
    angle_type: str
    topic: str | None = None
    status: str = "planned"


class ContentCalendarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: date
    day_of_week: int
    angle_type: str
    topic: str | None
    post_package_id: uuid.UUID | None
    weekly_guide_id: uuid.UUID | None
    status: str
    operator_notes: str | None
    is_buffer: bool
    buffer_priority: int
    created_at: datetime
    updated_at: datetime


class ContentCalendarUpdate(BaseModel):
    topic: str | None = None
    status: str | None = None
    operator_notes: str | None = None


class PlanWeekRequest(BaseModel):
    week_start: date
    weekly_theme: str | None = None
