"""VideoAsset model - rendered videos from Remotion templates."""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class VideoAsset(Base):
    __tablename__ = "video_assets"

    # References (one of these should be set)
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_packages.id"), nullable=True
    )
    guide_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weekly_guides.id"), nullable=True
    )

    # Template
    template_name: Mapped[str] = mapped_column(String(100))
    composition_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    composition_props: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Output
    video_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    video_s3_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Specs
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codec: Mapped[str | None] = mapped_column(String(20), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Rendering
    render_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    render_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Review
    operator_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Relationships
    post_package: Mapped["PostPackage"] = relationship(back_populates="video_assets")  # noqa: F821
    weekly_guide: Mapped["WeeklyGuide"] = relationship(back_populates="video_assets")  # noqa: F821
