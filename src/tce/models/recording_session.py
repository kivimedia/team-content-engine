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


class AgentTalk(Base):
    """One filmed voice call with an agent (3-Oct, contract C4, migration 057).

    The call's page records a selfie video with both voices and sends it in pieces while
    the call runs. The pieces live on disk beside each other (one file per sequence
    number); finishing the talk joins them, makes a library video with source
    "agent_talk", and starts its edit. A create sent twice (a retry) is the same talk:
    the call, its start and the agent identify it.
    """

    __tablename__ = "agent_talks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "agent", "call_id", "started_at", name="uq_agent_talk_identity"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(80))
    call_id: Mapped[str] = mapped_column(String(200), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    mime_type: Mapped[str] = mapped_column(String(120))
    file_extension: Mapped[str] = mapped_column(String(12))
    # recording | finished | failed
    status: Mapped[str] = mapped_column(String(20), default="recording", index=True)
    status_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_chunk_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What the finish found: pieces, bytes, missing sequence numbers, the container.
    join_meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recording_uploads.id", ondelete="SET NULL"), nullable=True, index=True
    )


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
