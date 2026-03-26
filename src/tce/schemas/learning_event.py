"""Schemas for LearningEvent."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class LearningEventCreate(BaseModel):
    package_id: uuid.UUID
    publish_date: date | None = None
    platform: str | None = None
    actual_comments: int | None = None
    actual_shares: int | None = None
    actual_clicks: int | None = None
    actual_dms: int | None = None
    actual_saves: int | None = None
    actual_follows: int | None = None
    operator_notes: str | None = None


class LearningEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID
    publish_date: date | None
    platform: str | None
    actual_comments: int | None
    actual_shares: int | None
    actual_clicks: int | None
    actual_dms: int | None
    actual_saves: int | None
    actual_follows: int | None
    postmortem_summary: str | None
    template_effectiveness_delta: float | None
    created_at: datetime
    updated_at: datetime
