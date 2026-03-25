"""Schemas for TrendBrief."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TrendBriefCreate(BaseModel):
    date: date
    brief_type: str = "daily"


class TrendBriefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: date
    brief_type: str
    trends: list[dict] | None
    selected_trend_ids: list[str] | None
    rejected_trend_ids: list[str] | None
    operator_additions: list[str] | None
    breaking_overrides: list[str] | None
    created_at: datetime
    updated_at: datetime
