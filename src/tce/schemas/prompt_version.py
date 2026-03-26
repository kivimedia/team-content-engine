"""Schemas for PromptVersion."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PromptVersionCreate(BaseModel):
    agent_name: str
    prompt_text: str
    variables: list[str] | None = None
    model_target: str | None = None
    created_by: str | None = None


class PromptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_name: str
    version: int
    prompt_text: str
    variables: list[str] | None
    model_target: str | None
    is_active: bool
    status: str
    ab_test_group: str | None
    performance_notes: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
