"""Evidence-first editorial records.

SourceRecord -> EvidenceMoment -> TopicCandidate -> RecordingPacket -> Publication

Tenant rule: every row here carries a NON-NULL workspace_id and is read with an
explicit `workspace_id == ws` filter. The legacy "NULL workspace is visible to
everyone" behaviour of the global filter must never apply to private evidence.

Privacy rule: raw transcripts, diffs and exact quotes live only in the
`*_private` columns. Anything named `public_*` must be safe to show outside the
editor view (no client names, customer words, credentials or money figures).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

# news_item and standing_fact belong to the third lane (models/news.py, migration
# 045). A news item is an announcement with its primary document; a standing fact
# is a hand-written durable fact about the business - a system Kivi Media runs for
# a category of client, or a problem the owners Ziv coaches keep bringing - which
# exists so those connections are citable at all. Both are inert until
# TCE_NEWS_LANE is on.
SOURCE_KINDS = ("fathom_meeting", "github_commit_group", "news_item", "standing_fact")
CLAIM_TYPES = ("quoted", "paraphrased", "inferred", "demonstrated", "measured")
REJECTION_GATES = (
    "small_service_business",
    "coach_or_event_owner_relevance",
    "concrete_supported_substance",
    "connects_to_ziv_work",
)
FEEDBACK_KINDS = ("approve", "source", "angle", "wording", "gate_reject", "note")


class _PrivateWorkspaceMixin:
    """Private evidence always belongs to exactly one workspace (NOT NULL in the DB)."""

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )


class EvidenceSource(_PrivateWorkspaceMixin, Base):
    """One external source item (a meeting, or a group of related commits)."""

    __tablename__ = "evidence_sources"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "source_kind", "external_id", name="uq_evidence_source_identity"
        ),
    )

    source_kind: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # sha256 of the normalized private payload; changes when a transcript is edited
    version_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # ok | partial (e.g. transcript missing) | failed | unavailable | excluded
    fetch_status: Mapped[str] = mapped_column(String(20), default="ok")
    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Private editor-only link (Fathom share URL, GitHub commit URL)
    url_private: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Private raw payload: transcript turns [{speaker, speaker_email?, start_s, end_s, text,
    # speaker_confidence, language}] or commits [{sha, repo, message, files:[{path,
    # patch_excerpt, blob_url_at_sha}], reverted_by?, reverts?}]
    payload_private: Mapped[dict[str, Any]] = mapped_column(JSONType)
    # Non-content metadata: participants count, repo full_name, commit shas, etc.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    last_collection_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class EvidenceCollectionRun(_PrivateWorkspaceMixin, Base):
    """Durable per-source coverage ledger for one bounded collection window."""

    __tablename__ = "evidence_collection_runs"

    source_kind: Mapped[str] = mapped_column(String(40))
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    # running | complete | partial | failed
    status: Mapped[str] = mapped_column(String(20), default="running")
    # {"listed": n, "in_window": n, "processed": n, "unchanged": n, "updated": n,
    #  "excluded": n, "failed": n, "unavailable": n, "pages": n}
    counts: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # [{"external_id", "state": processed|unchanged|updated|excluded|failed|unavailable,
    #   "reason"}]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # True only when pagination finished and no item is failed
    complete: Mapped[bool] = mapped_column(default=False)
    current_activity: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvidenceMoment(_PrivateWorkspaceMixin, Base):
    """A specific, citable span inside a source that could support a lesson."""

    __tablename__ = "evidence_moments"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True
    )
    source_version_hash: Mapped[str] = mapped_column(String(64))
    # meetings: seconds; commits: null
    span_start_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    span_end_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # commits: [{"repo", "sha", "path", "url_at_sha"}]
    code_refs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    # news_item / standing_fact: the third lane's locator, beside span_start_s for
    # meetings and code_refs for commits.
    # {"news_item_id", "primary_url", "publisher", "published_at", "quoted_span",
    #  "content_sha256", "source_version", "anchor_moment_ids"}
    news_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # high | medium | low | unknown - low when turns look interleaved or mislabeled
    speaker_confidence: Mapped[str] = mapped_column(String(10), default="unknown")
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # null when original language is used; otherwise e.g. "English adaptation from Hebrew"
    translation_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language_uncertain: Mapped[bool] = mapped_column(default=False)
    excerpt_private: Mapped[str] = mapped_column(Text)
    context_private: Mapped[str | None] = mapped_column(Text, nullable=True)
    lesson_summary: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(20))
    # ["client_identity", "customer_words", "health", "money", "credential", ...]
    sensitivity_flags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # active | stale (source edited after extraction) | discarded
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    extraction_job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class TopicCandidate(_PrivateWorkspaceMixin, Base):
    __tablename__ = "topic_candidates"

    week_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    selection_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    moment_ids: Mapped[list[str]] = mapped_column(JSONType)
    title: Mapped[str] = mapped_column(String(300))
    lesson: Mapped[str] = mapped_column(Text)
    # coaches | event_owners | both
    audience: Mapped[str] = mapped_column(String(20))
    reasons_to_care: Mapped[list[str]] = mapped_column(JSONType, default=list)
    public_angle: Mapped[str] = mapped_column(Text)
    public_safety_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {gate_name: {"pass": bool, "reason": str}} for all REJECTION_GATES
    gates: Mapped[dict[str, Any]] = mapped_column(JSONType)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # evergreen (freshness is a bonus) | news (claims need current verification)
    freshness_role: Mapped[str] = mapped_column(String(20), default="evergreen")
    # [{"moment_id", "source_kind", "title", "span", "url_private", "claim_type"}]
    citations_private: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # proposed | selected | rejected | recorded | published | withdrawn
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    editor_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Calibration rows (e.g. manually accepted sample ideas) are labelled here
    origin: Mapped[str] = mapped_column(String(30), default="selector")
    # Third lane. Present means news-led: the candidate cites a news_item moment
    # and must also cite a non-news one (enforce_candidates), so the announcement
    # is the trigger and a call, a commit or a standing fact is the point of view.
    news_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("news_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # When the claim stops being worth saying. A sweep sets meta.exclude_reason on
    # the source, which source_is_excluded() already drops from the pool.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EditorialFeedback(_PrivateWorkspaceMixin, Base):
    """Versioned editor preference. One rejection never silently bans a subject."""

    __tablename__ = "editorial_feedback"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    # approve | source | angle | wording | gate_reject | note
    kind: Mapped[str] = mapped_column(String(20))
    gate: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # publish | change_angle | not_for_me | null
    rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    preference_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RecordingPacket(_PrivateWorkspaceMixin, Base):
    __tablename__ = "recording_packets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "candidate_id", "version", name="uq_packet_version"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    bullets: Mapped[list[str]] = mapped_column(JSONType)  # 5-7 walking bullets
    script_phrases: Mapped[list[str]] = mapped_column(JSONType)  # one phrase per line
    facebook_post: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin_post: Mapped[str | None] = mapped_column(Text, nullable=True)
    interviewer_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Packet v2. Legacy rows keep these nullable and remain readable.
    hook_options: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    selected_hook_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    beats: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    citations_private: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # {"checked": bool, "issues": [...], "status": "clean"|"issues"|"unevaluated"}
    public_safety: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    google_doc_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    google_doc_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # {"intended": "...", "verified": bool, "detail": "..."}
    google_doc_access: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # draft | ready | exported | superseded
    status: Mapped[str] = mapped_column(String(20), default="draft")
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class ExportIntent(_PrivateWorkspaceMixin, Base):
    """Restart-safe identity for one packet-version Google Docs export."""

    __tablename__ = "export_intents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "packet_id", "packet_version", name="uq_export_intent"),
        UniqueConstraint("marker", name="uq_export_marker"),
    )

    packet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_packets.id", ondelete="CASCADE"), index=True
    )
    packet_version: Mapped[int] = mapped_column(Integer)
    marker: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(30), default="google_docs")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    document_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_readback: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordingUpload(_PrivateWorkspaceMixin, Base):
    """One uploaded file per idea; edits keep meaning and captions."""

    __tablename__ = "recording_uploads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_recording_upload_sha"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    packet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recording_packets.id", ondelete="SET NULL"), nullable=True
    )
    recording_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recording_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(300))
    storage_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64))
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    # [{"start_s","end_s","text"}] word/phrase timings from transcription
    transcript: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    # {"keep": [[start,end],...], "dropped": [{"start","end","text","reason"}],
    #  "meaning_check": {"status": "ok"|"blocked", "issues": [...]}}
    edit_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    captions_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    edited_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # uploaded | transcribing | planned | needs_review | edited | failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    status_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)


class PublicationReceipt(_PrivateWorkspaceMixin, Base):
    """Recorded after a human-authorised publication. TCE never publishes by itself here."""

    __tablename__ = "publication_receipts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "platform", "external_post_id", name="uq_publication_receipt"
        ),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    packet_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    platform: Mapped[str] = mapped_column(String(30))
    external_post_id: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"qualified_conversations": n, "strategy_sessions": n, "mentions": [...], ...}
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
