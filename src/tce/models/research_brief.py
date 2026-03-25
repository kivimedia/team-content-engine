"""ResearchBrief model — verified evidence for a topic."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class ResearchBrief(Base):
    __tablename__ = "research_briefs"

    topic: Mapped[str] = mapped_column(String(500))
    question_set: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # Claims (PRD Section 17)
    verified_claims: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    uncertain_claims: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    rejected_claims: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    # Sources
    source_refs: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    freshness_date: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Thesis
    thesis_candidates: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    risk_flags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    safe_to_publish: Mapped[bool | None] = mapped_column(default=None)
