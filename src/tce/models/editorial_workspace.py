"""Editorial workspace: the surfaces between "TCE found an idea" and "ready to record".

The recorder already knows how to capture a take. What it never had is a place to
think with an idea before committing a recording slot to it: a brief you can edit
field by field, a weekly lineup with real priorities, changes that are proposed and
reviewed rather than silently applied, and a conversation that knows which object
is on screen.

Tenant rule, inherited from `editorial.py`: every row here carries a NON-NULL
workspace_id. The "NULL workspace is visible to everyone" fallback of the global
filter must never apply to editorial content.

Privacy rule: nothing here stores raw transcript or diff text. A brief, a message
and a change operation hold references (`moment_id`, `source_id`) and bounded
excerpts that already passed the public-safety pass. The private payload stays in
`evidence_sources.payload_private`.

Versioning rule: `RecordingPacket` is already immutable per version. This module
adds the same discipline to the conceptual brief (`candidate_brief_versions`) and
gives both a shared review contract (`editorial_change_sets`). Applying a proposal
always writes a NEW version; it never mutates one that exists. Undo is another
version pointing back at known content, never a delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base
from tce.models.editorial import JSONType, _PrivateWorkspaceMixin

# ---------------------------------------------------------------------------
# Vocabularies. Kept as tuples so the API layer can validate against one source.
# ---------------------------------------------------------------------------

# The editable conceptual blocks of a topic, in the order the topic room shows
# them. `why_this_is_yours` is the one the selector must fill before an idea is
# allowed into the inbox at all.
BRIEF_FIELDS = (
    "topic",
    "audience",
    "big_idea",
    "why_now",
    "why_this_is_yours",
    "distinctive_perspective",
    "evidence",
    "claims_to_avoid",
    "takeaway",
    "cta",
)

BRIEF_ORIGINS = ("seed", "change_set", "manual", "undo")

# Where a topic sits for the editor. `inbox` is undecided, and it is the only
# state that offers the four first decisions.
TOPIC_DECISIONS = ("this_week", "discuss", "later", "away")

LINEUP_SLOTS = ("primary", "reserve")
LINEUP_STATUSES = ("draft", "active", "closed")
LINEUP_ITEM_STATUSES = ("planned", "preparing", "ready", "recorded", "dropped")

# Mix labels. Information for the editor, never a quota the server enforces.
LINEUP_LANES = ("build", "coaching", "ai_news", "other")

THREAD_CONTEXTS = ("topic", "packet", "week", "recording", "room")
THREAD_MODES = ("discuss", "propose", "review")
MESSAGE_ROLES = ("editor", "assistant", "system")
MESSAGE_STATUSES = ("complete", "queued", "failed")

CHANGE_TARGETS = ("candidate_brief", "packet", "lineup")
CHANGE_STATES = ("proposed", "applied", "rejected", "superseded", "invalid")
CHANGE_ORIGINS = ("conversation", "quick_action", "undo")

CHANGE_OPS = (
    "set_field",
    "replace_text",
    "choose_hook",
    "reorder_week",
    "move_topic",
    "restore_version",
    "request_edit",
)
CHANGE_OP_STATES = ("proposed", "accepted", "rejected", "applied", "skipped")

EDIT_REQUEST_SCOPES = ("whole", "timestamp", "section")
EDIT_REQUEST_STATES = ("open", "in_progress", "done", "rejected")


# ---------------------------------------------------------------------------
# The topic brief, versioned
# ---------------------------------------------------------------------------


class CandidateBriefVersion(_PrivateWorkspaceMixin, Base):
    """One immutable version of a topic's conceptual brief.

    Version 1 is backfilled from the `TopicCandidate` row itself so every existing
    idea has a brief without its content changing. Later versions are written only
    by applying a change set.
    """

    __tablename__ = "candidate_brief_versions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "candidate_id", "version", name="uq_candidate_brief_version"
        ),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    # The version this one was derived from. NULL on version 1. An undo points at
    # the version whose content it restores, so history stays a chain, not a reset.
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # {field: str} over BRIEF_FIELDS. Absent keys mean "not written yet" and render
    # as an empty block the editor can fill, never as an empty string.
    brief: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # seed | change_set | manual | undo
    origin: Mapped[str] = mapped_column(String(20), default="seed")
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TopicDecision(_PrivateWorkspaceMixin, Base):
    """The editor's first decision about a topic, separate from asking for a script.

    `TopicCandidate.status` stays the engine's word for where a topic is in the
    pipeline. This row is the editor's word, and the two are deliberately not the
    same column: putting a topic in this week is not the same act as paying for a
    script, and the old UI conflated them.
    """

    __tablename__ = "topic_decisions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "candidate_id", name="uq_topic_decision"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    # this_week | discuss | later | away
    decision: Mapped[str] = mapped_column(String(20), index=True)
    # Free text the editor attached when deciding. Survives put-away and restore.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Where it came back from, when it came back. Lets "Save for later" restore
    # without losing what was already decided once.
    previous_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)


# ---------------------------------------------------------------------------
# The weekly lineup
# ---------------------------------------------------------------------------


class WeeklyLineup(_PrivateWorkspaceMixin, Base):
    """The recording list for one local week.

    `revision` is the optimistic-concurrency token. Every mutation states the
    revision it read; a stale write is refused with the newer state rather than
    overwriting a reorder made on another device.
    """

    __tablename__ = "weekly_lineups"
    __table_args__ = (
        UniqueConstraint("workspace_id", "week_start", name="uq_weekly_lineup_week"),
    )

    week_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    # draft | active | closed
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # How many primary recording slots this week has. Three by default; stored so a
    # light week can be two without a code change.
    primary_slots: Mapped[int] = mapped_column(Integer, default=3)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


class WeeklyLineupItem(_PrivateWorkspaceMixin, Base):
    """One topic in one week, at one rank, in a primary slot or in reserve."""

    __tablename__ = "weekly_lineup_items"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "lineup_id", "candidate_id", name="uq_weekly_lineup_item"
        ),
    )

    lineup_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("weekly_lineups.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="CASCADE"), index=True
    )
    packet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recording_packets.id", ondelete="SET NULL"), nullable=True
    )
    # 1-based, contiguous within a slot. Rank 1 in `primary` is "Record first".
    rank: Mapped[int] = mapped_column(Integer, default=1)
    # primary | reserve
    slot: Mapped[str] = mapped_column(String(20), default="primary", index=True)
    # build | coaching | ai_news | other
    lane: Mapped[str] = mapped_column(String(20), default="other")
    # The human sentence shown beside the item: "Recommended first because it is
    # timely, connected to KM Bot, and explains a problem your clients face."
    # Never a numeric score. An opaque 87 looks precise and helps nobody decide.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # planned | preparing | ready | recorded | dropped
    status: Mapped[str] = mapped_column(String(20), default="planned")
    added_by: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class EditorialThread(_PrivateWorkspaceMixin, Base):
    """One conversation, bound to one object.

    There is exactly one thread per topic, packet, week and recording, plus one
    `room` thread per workspace for cross-topic decisions. The room's `context_id`
    is the workspace id, so the unique constraint holds without a nullable column.
    """

    __tablename__ = "editorial_threads"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "context_type", "context_id", name="uq_editorial_thread_context"
        ),
    )

    # topic | packet | week | recording | room
    context_type: Mapped[str] = mapped_column(String(20), index=True)
    context_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    # Denormalised so the thread list reads without joining four tables.
    context_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # open | closed
    status: Mapped[str] = mapped_column(String(20), default="open")
    # The mode the editor last used here, so reopening restores it.
    last_mode: Mapped[str] = mapped_column(String(20), default="discuss")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)


class EditorialMessage(_PrivateWorkspaceMixin, Base):
    """One turn in a thread.

    An assistant turn is written twice: once as `queued` when the LLM job is
    enqueued, then updated to `complete` when the worker returns. The queued row is
    what lets the phone show "Thinking about this topic" with a real job behind it
    instead of a spinner, and what lets a refresh restore a pending turn.
    """

    __tablename__ = "editorial_messages"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("editorial_threads.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=1)
    # editor | assistant | system
    role: Mapped[str] = mapped_column(String(20))
    # discuss | propose | review
    mode: Mapped[str] = mapped_column(String(20), default="discuss")
    text: Mapped[str] = mapped_column(Text, default="")
    # complete | queued | failed
    status: Mapped[str] = mapped_column(String(20), default="complete", index=True)
    status_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The proposal this turn produced, when the mode was `propose`.
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    # [{"kind": "moment"|"source"|"packet", "id": "...", "label": "...",
    #   "excerpt": "<= 400 chars, already public-safe"}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # {"job_id", "model", "prompt_version", "duration_ms"} - written by the worker.
    model_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)


# ---------------------------------------------------------------------------
# Proposed changes
# ---------------------------------------------------------------------------


class EditorialChangeSet(_PrivateWorkspaceMixin, Base):
    """A proposal against one object at one known version.

    Nothing an assistant says changes state. A change set is the only path from
    speech to stored content, and it is inert until a human accepts it. Rejecting
    keeps the row for audit; it is never deleted.
    """

    __tablename__ = "editorial_change_sets"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_editorial_change_set_idem"
        ),
    )

    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("editorial_threads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # candidate_brief | packet | lineup
    target_type: Mapped[str] = mapped_column(String(30), index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    # The version (brief/packet) or revision (lineup) this proposal was built on.
    # Applying against anything newer is refused and returns the newer state.
    base_version: Mapped[int] = mapped_column(Integer)
    # One plain sentence for the review sheet header.
    summary: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # proposed | applied | rejected | superseded | invalid
    state: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    # {"ok": bool, "issues": [{"code", "message", "op_seq"}]}
    validation: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # conversation | quick_action | undo
    origin: Mapped[str] = mapped_column(String(20), default="conversation")
    applied_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class EditorialChangeOperation(_PrivateWorkspaceMixin, Base):
    """One field-level operation inside a change set.

    Operations are accepted individually. `depends_on` names the sequence numbers
    an operation cannot be applied without, so a partial approval either keeps a
    bundle whole or tells the editor why it cannot.
    """

    __tablename__ = "editorial_change_operations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "change_set_id", "seq", name="uq_editorial_change_op_seq"
        ),
    )

    change_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("editorial_change_sets.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=1)
    # set_field | replace_text | choose_hook | reorder_week | move_topic |
    # restore_version | request_edit
    op: Mapped[str] = mapped_column(String(30))
    # Dotted path for packet sections ("bullets.2"), a BRIEF_FIELDS key for briefs,
    # NULL for whole-object operations such as reorder_week.
    field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Captured at proposal time so the review sheet can show a real before/after
    # and so a stale proposal is detectable by content, not only by version number.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # The one-line "why" shown under the diff.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # proposed | accepted | rejected | applied | skipped
    state: Mapped[str] = mapped_column(String(20), default="proposed")
    # [seq, ...] of operations in the same set this one requires.
    depends_on: Mapped[list[int]] = mapped_column(JSONType, default=list)


# ---------------------------------------------------------------------------
# After the recording
# ---------------------------------------------------------------------------


class EditingRequest(_PrivateWorkspaceMixin, Base):
    """A change the editor wants made to a finished recording.

    Scoped to the whole video, a timestamp range, or a named section of the packet.
    The raw upload is never replaced by acting on one of these.
    """

    __tablename__ = "editing_requests"

    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_uploads.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topic_candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    packet_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    packet_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # whole | timestamp | section
    scope: Mapped[str] = mapped_column(String(20), default="whole")
    start_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    section_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request: Mapped[str] = mapped_column(Text)
    # open | in_progress | done | rejected
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # What actually happened, with a pointer to the produced file when there is one.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
