"""Schemas for OperatorFeedback."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OperatorFeedbackCreate(BaseModel):
    package_id: uuid.UUID
    feedback_tags: list[str] | None = None
    feedback_notes: str | None = None
    action_taken: str  # approved/revised/rejected
    revision_summary: str | None = None
    created_by: str | None = None


class OperatorFeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    package_id: uuid.UUID
    feedback_tags: list[str] | None
    feedback_notes: str | None
    action_taken: str
    revision_summary: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
