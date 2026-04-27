"""Schemas for PostPackage."""

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _parse_json_str(v: Any) -> Any:
    """Parse JSON strings from SQLite back to Python objects."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            pass
    return v


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
    image_prompts: list[dict] | None
    approval_status: str
    is_archived: bool = False
    pipeline_run_id: uuid.UUID | None
    proof_trail: list[dict] | dict | None = None
    proof_status: str | None = None
    source: str | None = None
    source_repo_id: uuid.UUID | None = None
    source_repo_angle: str | None = None
    repo_url: str | None = None
    # Computed at list time: human-readable title derived from the source.
    # For repo: the repo name (display_name or slug tail). For topic: the
    # StoryBrief topic. For copy: a snippet of the post body. Else None.
    title: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("hook_variants", "image_prompts", "dm_flow", "quality_scores", "proof_trail", mode="before")
    @classmethod
    def parse_json_strings(cls, v: Any) -> Any:
        return _parse_json_str(v)


class PostPackageUpdate(BaseModel):
    facebook_post: str | None = None
    linkedin_post: str | None = None
    approval_status: str | None = None
    cta_keyword: str | None = None
    is_archived: bool | None = None
    hook_variants: list[str] | None = None
    dm_flow: dict | None = None


class PostPackageFull(PostPackageRead):
    """Extended read with nested QA and feedback."""

    qa_scorecard: dict | None = None
    operator_feedback: dict | None = None
