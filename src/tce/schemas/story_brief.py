"""Schemas for StoryBrief."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StoryBriefCreate(BaseModel):
    topic: str
    audience: str | None = None
    angle_type: str
    desired_belief_shift: str | None = None
    template_id: uuid.UUID | None = None
    house_voice_weights: dict | None = None
    thesis: str | None = None
    evidence_requirements: list[str] | None = None
    cta_goal: str | None = None
    visual_job: str | None = None


class StoryBriefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic: str
    audience: str | None
    angle_type: str
    desired_belief_shift: str | None
    template_id: uuid.UUID | None
    house_voice_weights: dict | None
    thesis: str | None
    evidence_requirements: list[str] | None
    cta_goal: str | None
    visual_job: str | None
    created_at: datetime
    updated_at: datetime
