"""Schemas for ContentCalendarEntry."""

import uuid
from datetime import date, datetime
from typing import Any

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
    plan_context: dict | None = None
    weekly_plan_id: uuid.UUID | None = None
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


class PlanWeekDeepRequest(BaseModel):
    week_start: date
    weekly_theme: str | None = None
    focus_areas: list[str] | None = None


class PlanApproveRequest(BaseModel):
    weekly_theme: str
    gift_theme: Any  # str or dict
    cta_keyword: str
    days: list[dict[str, Any]]
