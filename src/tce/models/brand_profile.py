"""BrandProfile model - per-client brand configuration for video templates."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    # Which creator this brand belongs to (nullable = global/default brand)
    creator_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creator_profiles.id"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(200))

    # Color scheme: {accent, accentDark, dark, overlay, text, textMuted, white,
    #                offWhite, error, success, gradientDark, gradientAccent}
    colors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Typography: {heading: "Poppins", body: "Open Sans"}
    fonts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Brand logo URL (optional)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # ElevenLabs voice config: {elevenlabs_voice_id, model, stability, similarity_boost}
    voice_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Notes / description
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    creator_profile: Mapped["CreatorProfile | None"] = relationship()  # noqa: F821
