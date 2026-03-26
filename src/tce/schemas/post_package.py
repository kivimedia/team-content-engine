"""Schemas for PostPackage."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PostPackageCreate(BaseModel):
    brief_id: uuid.UUID | None = None
    weekly_guide_id: uuid.UUID | None = None


class PostPackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brief_id: uuid.UUID | None
    weekly_guide_id: uuid.UUID | None
    facebook_post: str | None
    linkedin_post: str | None
    hook_variants: list[str] | None
    cta_keyword: str | None
    secondary_cta_keyword: str | None
    dm_flow: dict | None
    quality_scores: dict | None
    approval_status: str
    pipeline_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PostPackageUpdate(BaseModel):
    facebook_post: str | None = None
    linkedin_post: str | None = None
    approval_status: str | None = None
    cta_keyword: str | None = None


class PostPackageFull(PostPackageRead):
    """Extended read with nested QA and feedback."""

    qa_scorecard: dict | None = None
    operator_feedback: dict | None = None
