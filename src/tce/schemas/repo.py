"""Pydantic schemas for tracked repos and repo briefs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Angle = Literal["new_features", "whole_repo", "recent_fixes", "generic"]


class TrackedRepoCreate(BaseModel):
    """Register a new tracked repo."""

    repo_url: str = Field(..., description="GitHub URL, e.g. https://github.com/owner/name")
    display_name: str | None = None
    default_branch: str | None = None
    tags: list[str] | None = None
    include_examples_in_posts: bool = True
    blocked_topics: list[str] | None = None
    is_public: bool = True


class TrackedRepoUpdate(BaseModel):
    display_name: str | None = None
    default_branch: str | None = None
    tags: list[str] | None = None
    include_examples_in_posts: bool | None = None
    blocked_topics: list[str] | None = None
    is_archived: bool | None = None
    priority_score: float | None = None


class TrackedRepoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repo_url: str
    slug: str
    display_name: str | None = None
    default_branch: str
    description: str | None = None
    language: str | None = None
    is_public: bool = True
    is_archived: bool = False
    include_examples_in_posts: bool = True
    blocked_topics: list[str] | None = None
    tags: list[str] | None = None
    last_commit_sha: str | None = None
    last_commit_at: datetime | None = None
    last_scanned_at: datetime | None = None
    priority_score: float = 0.0
    created_at: datetime
    updated_at: datetime


class RepoScanRequest(BaseModel):
    """Trigger a fresh repo_scout run (no pipeline)."""

    angle: Angle = "generic"
    force_refresh: bool = False


class RepoBriefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tracked_repo_id: uuid.UUID
    angle: str
    commit_sha: str
    analyzed_at: datetime | None
    summary: str | None = None
    architecture_notes: str | None = None
    readme_excerpt: str | None = None
    recent_commits: list[Any] | None = None
    feature_highlights: list[Any] | None = None
    bug_fixes: list[Any] | None = None
    code_snippets: list[Any] | None = None
    package_hints: dict[str, Any] | None = None
    stats: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class StartFromRepoRequest(BaseModel):
    """Generate a full post package from a tracked repo with a chosen angle."""

    repo_id: uuid.UUID | None = None
    repo_url: str | None = Field(
        default=None,
        description="Ad hoc repo URL if not yet tracked. Either repo_id or repo_url is required.",
    )
    angle: Angle = "new_features"
    platform: Literal["facebook", "linkedin", "both"] = "both"
    cta_keyword: str | None = None
    include_video: bool = False
    language: str = "english"
    notes: str | None = None
    force_refresh: bool = Field(
        default=False,
        description="Skip the RepoBrief cache and always pull latest commits.",
    )
