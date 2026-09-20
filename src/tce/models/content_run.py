"""Durable content-run orchestration, scheduling and worker-group state."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


class ContentRun(Base):
    __tablename__ = "content_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_key", name="uq_content_run_request"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(160))
    normalized_scope_hash: Mapped[str] = mapped_column(String(64), index=True)
    scope_kind: Mapped[str] = mapped_column(String(30))
    source_ids_private: Mapped[list[str]] = mapped_column(JSONType, default=list)
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    week_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trigger_origin: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    maximum_candidate_count: Mapped[int] = mapped_column(Integer, default=6)
    target_packet_count: Mapped[int] = mapped_column(Integer, default=3)
    state: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    current_stage: Mapped[str] = mapped_column(String(30), default="collecting")
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    focused_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The last stage this run executes. "exporting" is a full run; the daily
    # evidence refresh stops after "extracting" and leaves generation to the
    # weekly run, which reuses every finished job.
    final_stage: Mapped[str] = mapped_column(
        String(30), default="exporting", server_default="exporting"
    )


class ContentRunStage(Base):
    __tablename__ = "content_run_stages"
    __table_args__ = (UniqueConstraint("run_id", "stage", name="uq_content_run_stage"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(30), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    input_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    job_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    output_refs: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_eligible_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StageResultCache(Base):
    __tablename__ = "stage_result_cache"
    __table_args__ = (UniqueConstraint("workspace_id", "cache_key", name="uq_stage_result_cache"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(30), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_versions: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONType)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class EditorialSchedule(Base):
    __tablename__ = "editorial_schedules"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_editorial_schedule_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Jerusalem")
    weekday: Mapped[int] = mapped_column(Integer, default=0)
    local_time: Mapped[str] = mapped_column(String(5), default="07:00")
    catchup_days: Mapped[int] = mapped_column(Integer, default=7)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # "weekly" fires on `weekday` at `local_time`; "daily" fires every day at
    # `local_time`. Both are evaluated in `timezone`, so Israel DST needs no
    # special casing here or in cron (the launcher ticks often, this decides).
    cadence: Mapped[str] = mapped_column(String(20), default="weekly", server_default="weekly")
    # Stage the created run stops after. The daily evidence refresh stops at
    # "extracting"; the weekly content run goes through "exporting".
    final_stage: Mapped[str] = mapped_column(
        String(30), default="exporting", server_default="exporting"
    )
    # Days of evidence each occurrence covers, ending at the occurrence.
    window_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")


class EditorialScheduleOccurrence(Base):
    __tablename__ = "editorial_schedule_occurrences"
    __table_args__ = (
        UniqueConstraint("schedule_id", "occurrence_key", name="uq_editorial_occurrence"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("editorial_schedules.id", ondelete="CASCADE"), index=True
    )
    occurrence_key: Mapped[str] = mapped_column(String(100))
    scheduled_for_utc: Mapped[datetime] = mapped_column(DateTime, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(30), default="queued")
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    content_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_runs.id", ondelete="SET NULL"), nullable=True
    )


class WorkerGroupState(Base):
    __tablename__ = "worker_group_states"
    __table_args__ = (UniqueConstraint("group_key", name="uq_worker_group_key"),)

    group_key: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(30), default="available", index=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
