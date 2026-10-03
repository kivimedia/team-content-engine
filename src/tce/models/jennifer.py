"""Jennifer, the video editor: what she found on each render, and the rules she learned.

3-Oct (migration 058). Two tables, both private to one workspace:

- `render_checks`: one row per check of one render. After every render she measures
  the file itself (pauses, leftover asides, every word heard, captions, loudness),
  fixes what a cut can fix, and holds the video only for what she cannot. The row is
  the record of that check; the newest one is also kept on the video (`qc`).
- `editor_rules`: a note he gave on one video, distilled into a rule for every next
  video. Deleting a rule on the rules page switches it off (`active` false); the row
  stays, so the history of what she learned and from which video is never lost.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


class RenderCheck(Base):
    """One check of one render: what was measured, what was fixed, and the verdict."""

    __tablename__ = "render_checks"

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recording_uploads.id", ondelete="CASCADE"), index=True
    )
    # The render this check measured (recording_uploads.render_ref at that moment).
    render_ref: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    # 0: the first check of an edit. 1: the re-check after her one fix and re-render.
    round: Mapped[int] = mapped_column(Integer, default=0)
    # passed | fixing | fixed | held | report | unchecked
    state: Mapped[str] = mapped_column(String(20), default="passed", index=True)
    # The one plain line the card and her voice seat show.
    line: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # {"numbers": {...}, "checks": {"gaps": {...}, ...}, "fixes": [...]}
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class EditorRule(Base):
    """One rule Jennifer learned from a note on a video, applied to every next video."""

    __tablename__ = "editor_rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # One plain sentence: "Cut any aside to the dogs, even under 2 seconds."
    text: Mapped[str] = mapped_column(Text)
    # The video and the note it came from. Kept when either is deleted (SET NULL).
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recording_uploads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("editing_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Delete on the rules page switches a rule off; the row stays.
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # How many videos a cut of hers named this rule on, and which (ids as text), so the
    # same video edited again does not count twice.
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    applied_uploads: Mapped[list[str]] = mapped_column(JSONType, default=list)
