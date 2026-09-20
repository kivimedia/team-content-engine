"""Append-only mobile recording sessions, clips and chunk manifests."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


class RecordingSession(Base):
    __tablename__ = "recording_sessions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "candidate_id", "packet_id", "retake_index",
            name="uq_recording_session_retake",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    packet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_packets.id", ondelete="RESTRICT"), index=True
    )
    packet_version: Mapped[int] = mapped_column(Integer)
    retake_index: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    active_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    selected_clip_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    timeline_map: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    canonical_upload_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    device_meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordingClip(Base):
    __tablename__ = "recording_clips"
    __table_args__ = (
        UniqueConstraint("session_id", "local_clip_id", name="uq_recording_clip_local"),
        UniqueConstraint("session_id", "position", name="uq_recording_clip_position"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_sessions.id", ondelete="CASCADE"), index=True
    )
    local_clip_id: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="recording", index=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    file_extension: Mapped[str] = mapped_column(String(12))
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    assembled_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    take_markers: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    timing_meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordingChunk(Base):
    __tablename__ = "recording_chunks"
    __table_args__ = (
        UniqueConstraint("clip_id", "sequence", name="uq_recording_chunk_sequence"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    clip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_clips.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1000))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
