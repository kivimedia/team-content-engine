"""Schemas for CreatorProfile."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreatorProfileCreate(BaseModel):
    creator_name: str
    source_urls: list[str] | None = None
    style_notes: str | None = None
    allowed_influence_weight: float = 0.20
    disallowed_clone_markers: list[str] | None = None
    top_patterns: list[str] | None = None
    voice_axes: dict | None = None


class CreatorProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    creator_name: str
    source_urls: list[str] | None
    style_notes: str | None
    allowed_influence_weight: float
    disallowed_clone_markers: list[str] | None
    top_patterns: list[str] | None
    voice_axes: dict | None
    created_at: datetime
    updated_at: datetime


class CreatorProfileUpdate(BaseModel):
    creator_name: str | None = None
    style_notes: str | None = None
    allowed_influence_weight: float | None = None
    voice_axes: dict | None = None
