"""VideoLeadScript model - long-form talking-head video scripts."""

import uuid

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class VideoLeadScript(Base):
    __tablename__ = "video_lead_scripts"

    # Content
    title: Mapped[str] = mapped_column(String(500), default="Untitled")
    title_pattern: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    sections: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Metadata
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_takeaway: Mapped[str | None] = mapped_column(Text, nullable=True)
    niche: Mapped[str] = mapped_column(String(50), default="coaching")

    # SEO / Repurpose
    seo_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    blog_repurpose_outline: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status: draft -> approved -> recorded -> repurposed
    status: Mapped[str] = mapped_column(String(30), default="draft")

    # Pipeline reference
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Story brief reference (topic/thesis that generated this)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
