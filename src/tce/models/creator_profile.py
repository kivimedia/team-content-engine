"""CreatorProfile model — source creators in the influence pool."""

import uuid

from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class CreatorProfile(Base):
    __tablename__ = "creator_profiles"

    creator_name: Mapped[str] = mapped_column(String(200))
    source_urls: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    style_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_influence_weight: Mapped[float] = mapped_column(Float, default=0.20)
    disallowed_clone_markers: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    top_patterns: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    voice_axes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    post_examples: Mapped[list["PostExample"]] = relationship(  # noqa: F821
        back_populates="creator", cascade="all, delete-orphan"
    )
