"""WalkingVideoScript model - short (60-120s) walking-monologue video scripts.

Distinct from VideoLeadScript because the output shape and lifecycle differ:
  - Single continuous monologue (no sections array)
  - Shot notes + cutsense_prompt specific to handheld vertical capture
  - Status chain: draft -> approved -> recorded -> edited -> published
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class WalkingVideoScript(Base):
    __tablename__ = "walking_video_scripts"

    # Content
    title: Mapped[str] = mapped_column(String(500), default="Untitled")
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_formula: Mapped[str | None] = mapped_column(String(5), nullable=True)
    full_script: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Walking-specific metadata
    shot_notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cutsense_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    format_label: Mapped[str] = mapped_column(String(50), default="walking_monologue")

    # Timing + size
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_target_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Story context
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    niche: Mapped[str] = mapped_column(String(50), default="general")

    # Style anchor: which corpus creator we emulated (TJ, etc)
    creator_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creator_profiles.id", ondelete="SET NULL"), nullable=True
    )

    # SEO + repurpose
    seo_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    repurpose: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Lifecycle
    # draft | approved | recorded | edited | published | rejected | archived
    status: Mapped[str] = mapped_column(String(30), default="draft")
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    video_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operator captures - revision notes, approval rationale, "tune next time"
    operator_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline reference
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
