"""PostPackage model — complete daily content package (FB + LI + CTA + visuals)."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class PostPackage(Base):
    __tablename__ = "post_packages"

    # References
    brief_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("story_briefs.id"), nullable=True)
    research_brief_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_briefs.id"), nullable=True
    )
    weekly_guide_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weekly_guides.id"), nullable=True
    )

    # Content
    facebook_post: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin_post: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_variants: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # CTA
    cta_keyword: Mapped[str | None] = mapped_column(String(100), nullable=True)
    secondary_cta_keyword: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dm_flow: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Quality
    quality_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="draft")

    # Image generation prompts from Creative Director
    image_prompts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Pipeline metadata
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Archive
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # A/B testing (PRD Section 43.2)
    experiment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    image_assets: Mapped[list["ImageAsset"]] = relationship(  # noqa: F821
        back_populates="post_package", cascade="all, delete-orphan"
    )
    qa_scorecard: Mapped["QAScorecard | None"] = relationship(  # noqa: F821
        back_populates="post_package", uselist=False
    )
    operator_feedback: Mapped["OperatorFeedback | None"] = relationship(  # noqa: F821
        back_populates="post_package", uselist=False
    )
    learning_event: Mapped["LearningEvent | None"] = relationship(  # noqa: F821
        back_populates="post_package", uselist=False
    )
    video_assets: Mapped[list["VideoAsset"]] = relationship(  # noqa: F821
        back_populates="post_package", cascade="all, delete-orphan"
    )
    narration_scripts: Mapped[list["NarrationScript"]] = relationship(  # noqa: F821
        back_populates="post_package", cascade="all, delete-orphan"
    )
