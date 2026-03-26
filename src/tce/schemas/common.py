"""Shared schema components — enums, pagination, base types."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


class Platform(StrEnum):
    FACEBOOK = "facebook"
    LINKEDIN = "linkedin"


class ApprovalStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class PassStatus(StrEnum):
    PENDING = "pending"
    PASS = "pass"
    CONDITIONAL_PASS = "conditional_pass"
    FAIL = "fail"


class PromptStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class FeedbackAction(StrEnum):
    APPROVED = "approved"
    REVISED = "revised"
    REJECTED = "rejected"


class EngagementConfidence(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class AngleType(StrEnum):
    BIG_SHIFT = "big_shift_explainer"
    WORKFLOW_TOOL = "tactical_workflow_guide"
    CONTRARIAN = "contrarian_diagnosis"
    CASE_STUDY = "case_study_build_story"
    STRATEGIC = "second_order_implication"
    ROUNDUP = "weekly_roundup"
    FOUNDER_REFLECTION = "founder_reflection"
    TEARDOWN = "teardown_myth_busting"


# QA dimension names (PRD Section 45.2)
QA_DIMENSIONS = [
    "evidence_completeness",
    "freshness",
    "clarity",
    "novelty",
    "non_cloning",
    "audience_fit",
    "cta_honesty",
    "platform_fit",
    "visual_coherence",
    "house_voice_fit",
    "humanitarian_sensitivity",
    "founder_voice_alignment",
]

# QA dimension weights (PRD Section 45.2)
QA_WEIGHTS: dict[str, float] = {
    "evidence_completeness": 0.12,
    "freshness": 0.08,
    "clarity": 0.12,
    "novelty": 0.08,
    "non_cloning": 0.12,
    "audience_fit": 0.08,
    "cta_honesty": 0.08,
    "platform_fit": 0.05,
    "visual_coherence": 0.05,
    "house_voice_fit": 0.05,
    "humanitarian_sensitivity": 0.10,
    "founder_voice_alignment": 0.07,
}

# QA pass thresholds per dimension
QA_THRESHOLDS: dict[str, int] = {
    "evidence_completeness": 7,
    "freshness": 7,
    "clarity": 7,
    "novelty": 6,
    "non_cloning": 8,
    "audience_fit": 7,
    "cta_honesty": 9,
    "platform_fit": 7,
    "visual_coherence": 6,
    "house_voice_fit": 7,
    "humanitarian_sensitivity": 8,
    "founder_voice_alignment": 7,
}

# Feedback taxonomy tags (PRD Section 46.2)
FEEDBACK_TAGS = [
    # Hook issues
    "hook_too_aggressive",
    "hook_too_weak",
    "hook_wrong_angle",
    "hook_too_similar",
    # Thesis issues
    "thesis_unclear",
    "thesis_unsupported",
    "thesis_wrong_audience",
    "thesis_too_obvious",
    # Structure issues
    "structure_too_long",
    "structure_too_short",
    "structure_bad_flow",
    "structure_wrong_template",
    # CTA issues
    "cta_unfulfillable",
    "cta_too_pushy",
    "cta_missing",
    "cta_wrong_keyword",
    # Voice issues
    "voice_too_clone",
    "voice_too_generic",
    "voice_wrong_tone",
    "voice_wrong_platform",
    # Visual issues
    "visual_mismatch",
    "visual_too_generic",
    "visual_wrong_mood",
    # Research issues
    "research_stale",
    "research_missing",
    "research_wrong_source",
]


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime


class IDMixin(BaseModel):
    id: uuid.UUID
