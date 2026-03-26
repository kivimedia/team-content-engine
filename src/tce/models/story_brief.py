"""StoryBrief model — daily angle selection from the Story Strategist."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class StoryBrief(Base):
    __tablename__ = "story_briefs"

    topic: Mapped[str] = mapped_column(String(500))
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    angle_type: Mapped[str] = mapped_column(String(100))
    desired_belief_shift: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Template
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pattern_templates.id"), nullable=True
    )

    # Voice
    house_voice_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Thesis
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_requirements: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Goals
    cta_goal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visual_job: Mapped[str | None] = mapped_column(String(100), nullable=True)
    platform_notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
