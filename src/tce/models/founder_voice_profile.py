"""FounderVoiceProfile model — the operator's authentic voice extracted from books/posts."""

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class FounderVoiceProfile(Base):
    __tablename__ = "founder_voice_profiles"

    # Source documents used for extraction
    source_document_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # Extracted voice characteristics (PRD Section 50.5)
    vocabulary_signature: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sentence_rhythm_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    values_and_beliefs: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    metaphor_families: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tone_range: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    taboos: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    recurring_themes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    humor_type: Mapped[str | None] = mapped_column(Text, nullable=True)
