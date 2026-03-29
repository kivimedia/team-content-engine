"""RenderQueue model - tracks video render jobs with status and progress."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class RenderQueueJob(Base):
    __tablename__ = "render_queue"

    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_packages.id"), nullable=True
    )
    guide_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weekly_guides.id"), nullable=True
    )

    # Job spec
    template_name: Mapped[str] = mapped_column(String(100))
    composition_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    composition_props: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Output
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("video_assets.id"), nullable=True
    )
    output_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Timing
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    render_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
