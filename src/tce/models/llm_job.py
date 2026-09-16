"""Durable subscription LLM job queue.

Every text-generation call in TCE becomes one row here. A Claude Code worker
authenticated to a subscription leases the row, runs one bounded prompt with
an optional JSON schema, and writes the result back under its attempt ID.
Nothing in TCE calls a metered model API directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

# queued -> leased -> succeeded | failed | waiting_capacity (-> leased again) | cancelled
LLM_JOB_STATUSES = (
    "queued",
    "leased",
    "succeeded",
    "failed",
    "waiting_capacity",
    "cancelled",
)


class LLMJob(Base):
    __tablename__ = "llm_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_llm_jobs_idempotency_key"),)

    job_type: Mapped[str] = mapped_column(String(80))
    agent_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))

    # Request: {"system": str|None, "messages": [...], "output_schema": {...}|None,
    #           "max_tokens": int}
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONType)
    requested_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    output_schema_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)

    # Leasing
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Result
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[Any | None] = mapped_column(JSONType, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Receipt: actual models (all of modelUsage), auth_method, api_provider,
    # api_key_source, cli_version, session_id, duration_ms, worker_host.
    # Never contains credentials.
    receipt_json: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
