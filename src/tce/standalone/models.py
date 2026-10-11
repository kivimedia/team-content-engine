"""Standalone account and tenant records. Every private object has a workspace ID."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base
from tce.models.editorial import JSONType
from tce.standalone.crypto import EncryptedText


class StandaloneAccount(Base):
    __tablename__ = "standalone_accounts"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandaloneWorkspace(Base):
    __tablename__ = "standalone_workspaces"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="UTC", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StandaloneMembership(Base):
    __tablename__ = "standalone_memberships"
    __table_args__ = (UniqueConstraint("account_id", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StandaloneSession(Base):
    __tablename__ = "standalone_sessions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandaloneAPIToken(Base):
    __tablename__ = "standalone_api_tokens"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandaloneInvite(Base):
    __tablename__ = "standalone_invites"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandaloneConfigRevision(Base):
    __tablename__ = "standalone_config_revisions"
    __table_args__ = (UniqueConstraint("workspace_id", "revision"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(24), nullable=False)


class StandaloneOnboardingDraft(Base):
    __tablename__ = "standalone_onboarding_drafts"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), unique=True, nullable=False
    )
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StandaloneMaterial(Base):
    __tablename__ = "standalone_materials"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "sha256"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    lane_index: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    readable_page_count: Mapped[int | None] = mapped_column(Integer)


class StandaloneSecret(Base):
    __tablename__ = "standalone_secrets"
    __table_args__ = (UniqueConstraint("workspace_id", "kind"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandaloneDelivery(Base):
    __tablename__ = "standalone_deliveries"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    render_id: Mapped[uuid.UUID | None] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_receipt: Mapped[str | None] = mapped_column(String(250))
    error_code: Mapped[str | None] = mapped_column(String(80))


class StandaloneSourceItem(Base):
    __tablename__ = "standalone_source_items"
    __table_args__ = (UniqueConstraint("workspace_id", "lane_index", "external_id", "sha256"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    lane_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StandaloneIdea(Base):
    __tablename__ = "standalone_ideas"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("standalone_source_items.id")
    )
    lane_index: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(EncryptedText("idea.title"), nullable=False)
    angle: Mapped[str] = mapped_column(EncryptedText("idea.angle"), nullable=False)
    why_now: Mapped[str] = mapped_column(EncryptedText("idea.why_now"), default="", nullable=False)
    evidence: Mapped[str] = mapped_column(
        EncryptedText("idea.evidence"), default="", nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="inbox", nullable=False)
    week_start: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str] = mapped_column(EncryptedText("idea.notes"), default="", nullable=False)


class StandaloneScriptVersion(Base):
    __tablename__ = "standalone_script_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "idea_id", "version"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("standalone_ideas.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    script: Mapped[str] = mapped_column(EncryptedText("script.script"), nullable=False)
    note: Mapped[str] = mapped_column(EncryptedText("script.note"), default="", nullable=False)
    origin: Mapped[str] = mapped_column(String(24), default="generated", nullable=False)


class StandaloneRecording(Base):
    __tablename__ = "standalone_recordings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("standalone_ideas.id"), nullable=False)
    script_version: Mapped[int | None] = mapped_column(Integer)
    original_key: Mapped[str] = mapped_column(String(500), nullable=False)
    edited_key: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="uploaded", nullable=False)
    qc: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class StandaloneChatMessage(Base):
    __tablename__ = "standalone_chat_messages"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    context: Mapped[str] = mapped_column(String(30), nullable=False)
    context_id: Mapped[uuid.UUID | None] = mapped_column()
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class StandaloneJob(Base):
    __tablename__ = "standalone_jobs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    phase: Mapped[str] = mapped_column(String(160), default="Queued", nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error_code: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StandaloneRoutineRun(Base):
    __tablename__ = "standalone_routine_runs"
    __table_args__ = (UniqueConstraint("workspace_id", "routine_date"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    routine_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="running", nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("standalone_jobs.id"))
    error_code: Mapped[str | None] = mapped_column(String(80))


class StandaloneLiveSession(Base):
    __tablename__ = "standalone_live_sessions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_accounts.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    context_id: Mapped[uuid.UUID | None] = mapped_column()
    provider_session_id: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="started", nullable=False)


class StandaloneRender(Base):
    __tablename__ = "standalone_renders"
    __table_args__ = (UniqueConstraint("workspace_id", "recording_id", "version"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_workspaces.id"), nullable=False
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("standalone_recordings.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    start_s: Mapped[int] = mapped_column(Integer, nullable=False)
    end_s: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
