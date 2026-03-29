"""NarrationScript model - voiceover scripts with segment data and audio alignment."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class NarrationScript(Base):
    __tablename__ = "narration_scripts"

    # Reference
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_packages.id"), nullable=True
    )

    # Script content
    template_style: Mapped[str] = mapped_column(String(50))
    segments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Status: draft -> ready_to_record -> audio_uploaded -> aligned -> rendered
    status: Mapped[str] = mapped_column(String(30), default="draft")

    # Audio
    audio_file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    audio_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_format: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Whisper alignment
    whisper_transcript: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    alignment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Estimates
    estimated_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Rendered output
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("video_assets.id"), nullable=True
    )

    # Pipeline
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Relationships
    post_package: Mapped["PostPackage | None"] = relationship(back_populates="narration_scripts")  # noqa: F821
    video_asset: Mapped["VideoAsset | None"] = relationship()  # noqa: F821
