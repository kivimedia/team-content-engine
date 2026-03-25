"""Schemas for PostExample."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PostExampleCreate(BaseModel):
    document_id: uuid.UUID
    creator_id: uuid.UUID
    page_number: int | None = None
    post_text_raw: str | None = None
    hook_text: str | None = None
    body_text: str | None = None
    cta_text: str | None = None
    hook_type: str | None = None
    body_structure: str | None = None
    story_arc: str | None = None
    tension_type: str | None = None
    cta_type: str | None = None
    visual_type: str | None = None
    visible_comments: int | None = None
    visible_shares: int | None = None
    engagement_confidence: str = "C"


class PostExampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    creator_id: uuid.UUID
    page_number: int | None
    post_text_raw: str | None
    hook_text: str | None
    body_text: str | None
    cta_text: str | None
    hook_type: str | None
    body_structure: str | None
    story_arc: str | None
    tension_type: str | None
    cta_type: str | None
    visual_type: str | None
    tone_tags: list[str] | None
    topic_tags: list[str] | None
    visible_comments: int | None
    visible_shares: int | None
    engagement_confidence: str
    raw_score: float | None
    final_score: float | None
    manual_review_status: str
    created_at: datetime
    updated_at: datetime
