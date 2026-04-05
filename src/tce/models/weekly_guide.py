"""WeeklyGuide model — shared weekly lead magnet (DOCX guide)."""

from datetime import date

from sqlalchemy import Boolean, Date, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class WeeklyGuide(Base):
    __tablename__ = "weekly_guides"

    week_start_date: Mapped[date] = mapped_column(Date)
    weekly_theme: Mapped[str] = mapped_column(String(500))
    guide_title: Mapped[str] = mapped_column(String(500))

    # Files
    docx_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # CTA
    cta_keyword: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dm_flow: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fulfillment_link: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Metrics
    downloads_count: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Quality scores (LLM-assessed)
    quality_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)
    assessment_history: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quality_gate_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Archive
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # Operator
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    video_assets: Mapped[list["VideoAsset"]] = relationship(  # noqa: F821
        back_populates="weekly_guide", cascade="all, delete-orphan"
    )
