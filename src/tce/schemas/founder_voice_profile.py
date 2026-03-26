"""Schemas for FounderVoiceProfile."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FounderVoiceProfileCreate(BaseModel):
    source_document_ids: list[str] | None = None
    values_and_beliefs: list[str] | None = None
    metaphor_families: list[str] | None = None
    taboos: list[str] | None = None
    recurring_themes: list[str] | None = None


class FounderVoiceProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_document_ids: list[str] | None
    vocabulary_signature: dict | None
    sentence_rhythm_profile: dict | None
    values_and_beliefs: list[str] | None
    metaphor_families: list[str] | None
    tone_range: dict | None
    taboos: list[str] | None
    recurring_themes: list[str] | None
    humor_type: str | None
    created_at: datetime
    updated_at: datetime
