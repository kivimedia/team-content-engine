"""Schemas for WeeklyGuide."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class WeeklyGuideCreate(BaseModel):
    week_start_date: date
    weekly_theme: str
    guide_title: str
    cta_keyword: str | None = None


class WeeklyGuideRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    week_start_date: date
    weekly_theme: str
    guide_title: str
    docx_path: str | None
    pdf_path: str | None
    markdown_content: str | None
    cta_keyword: str | None
    fulfillment_link: str | None
    downloads_count: int
    conversion_rate: float | None
    quality_scores: dict | None = None
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime
