"""Schemas for ResearchBrief."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ResearchBriefCreate(BaseModel):
    topic: str
    question_set: list[str] | None = None


class ResearchBriefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic: str
    question_set: list[str] | None
    verified_claims: list[dict] | None
    uncertain_claims: list[dict] | None
    rejected_claims: list[dict] | None
    source_refs: list[dict] | None
    freshness_date: str | None
    thesis_candidates: list[str] | None
    risk_flags: list[str] | None
    safe_to_publish: bool | None
    created_at: datetime
    updated_at: datetime
