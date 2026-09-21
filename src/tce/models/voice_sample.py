"""A stretch of Ziv actually talking, kept so the writer can hear him.

Fathom stores every meeting turn with a speaker email, so his own speech is
identifiable exactly. One row here is a run of consecutive turns by him: a mini
speech, which is the unit he thinks in ("keep my mini speeches"), not a 58-character
conversational turn.

Private by construction. These are his words from client calls; they exist to shape
how a script sounds, never to be quoted on camera.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base
from tce.models.editorial import JSONType


class VoiceSample(Base):
    """One mini speech: consecutive turns by one speaker in one call."""

    __tablename__ = "voice_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_sources.id", ondelete="CASCADE"), index=True
    )
    # Where in the call, so a sample can be found and listened to again.
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_turn_index: Mapped[int] = mapped_column(Integer)
    turn_count: Mapped[int] = mapped_column(Integer, default=1)
    start_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    language: Mapped[str] = mapped_column(String(20), default="en", index=True)
    text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # The first sentence on its own: this is the bank his openings are drawn from.
    opening: Mapped[str | None] = mapped_column(Text, nullable=True)

    # teaching | operating | thin. Only "teaching" is shown to a writer; the rest are
    # kept so a filter change can be re-judged without rebuilding from transcripts.
    kind: Mapped[str] = mapped_column(String(20), default="teaching", index=True)
    kind_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Content words, stored so retrieval does not re-tokenise the whole corpus.
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "source_title": self.source_title,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "word_count": self.word_count,
            "opening": self.opening,
            "text": self.text,
        }
