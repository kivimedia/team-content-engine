"""WeeklyWalkingRecording model - one long video per week covering all 5 walking scripts.

Lifecycle:
  uploaded -> transcribing -> aligning -> splitting -> editing -> done | failed

transcript_json and alignment_json are preserved so reruns don't retranscribe/realign.
cutsense_jobs maps script_id -> CutSense job_id for each per-clip edit job.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class WeeklyWalkingRecording(Base):
    __tablename__ = "weekly_walking_recordings"

    # The week this recording belongs to
    weekly_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("weekly_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Path to the single long video on the VPS
    long_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle state: uploaded | transcribing | aligning | splitting | editing | done | failed
    status: Mapped[str] = mapped_column(String(30), default="uploaded", nullable=False)

    # Human-readable error when status=failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Word-level transcript from faster-whisper (preserved to skip retranscription on rerun)
    transcript_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Alignment result: list of {script_id, start_sec, end_sec, anchor_text, match_confidence}
    alignment_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Map of script_id -> CutSense job_id for each per-clip edit job
    cutsense_jobs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timestamps for stage transitions
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aligned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    split_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    editing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Pipeline run that manages this recording's workflow
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
