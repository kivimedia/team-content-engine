"""Schemas for PatternTemplate."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PatternTemplateCreate(BaseModel):
    template_name: str
    template_family: str
    best_for: str | None = None
    hook_formula: str | None = None
    body_formula: str | None = None
    proof_requirements: str | None = None
    cta_compatibility: list[str] | None = None
    visual_compatibility: list[str] | None = None
    platform_fit: str | None = None
    tone_profile: dict | None = None
    risk_notes: str | None = None
    anti_patterns: str | None = None
    source_influence_weights: dict | None = None


class PatternTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_name: str
    template_family: str
    best_for: str | None
    hook_formula: str | None
    body_formula: str | None
    cta_compatibility: list[str] | None
    visual_compatibility: list[str] | None
    platform_fit: str | None
    tone_profile: dict | None
    risk_notes: str | None
    anti_patterns: str | None
    source_influence_weights: dict | None
    example_ids: list[str] | None
    median_score: float | None
    sample_size: int
    confidence_avg: float | None
    creator_diversity_count: int
    proof_requirements: str | None
    best_for: str | None
    status: str
    created_at: datetime
    updated_at: datetime
