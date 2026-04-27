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
    walking_video_script_id: uuid.UUID | None = None
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
    sensitive_period: bool = False
    humanitarian_context: str | None = None
    # Video Studio integration: reserve one or more weekday slots for walking
    # video scripts. For each selected day, the planner prefers walking-friendly
    # angles (hot takes, contrarian reframes, news reactions) and marks
    # plan_context.content_format = "walking_video" so the dashboard renders
    # those cards differently and routes Generate clicks to Video Studio
    # instead of the text pipeline.
    # Values are weekday indices 0=Monday .. 4=Friday. Empty = no video days.
    # Legacy scalar `video_day_weekday` still accepted (auto-promoted to list).
    video_day_weekdays: list[int] | None = None
    video_day_weekday: int | None = None  # deprecated - use video_day_weekdays

    def resolved_video_days(self) -> set[int]:
        """Merge legacy + new fields into the canonical set of video weekday indices."""
        days: set[int] = set()
        if self.video_day_weekdays:
            days.update(d for d in self.video_day_weekdays if 0 <= d <= 4)
        if self.video_day_weekday is not None and 0 <= self.video_day_weekday <= 4:
            days.add(self.video_day_weekday)
        return days


class PlanApproveRequest(BaseModel):
    weekly_theme: str
    gift_theme: Any  # str or dict; ignored when gift_skipped is True
    cta_keyword: str
    days: list[dict[str, Any]]
    # -1 means "no gift this week" (gift_skipped also true). 0/1/2 selects
    # the corresponding GuideOption row. Defaults to 0 for backward compat.
    selected_guide_index: int = 0
    gift_skipped: bool = False
