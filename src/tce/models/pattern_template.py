"""PatternTemplate model — reusable post structures mined from the corpus."""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class PatternTemplate(Base):
    __tablename__ = "pattern_templates"

    template_name: Mapped[str] = mapped_column(String(200))
    template_family: Mapped[str] = mapped_column(String(100))
    best_for: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structure
    hook_formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Compatibility
    cta_compatibility: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    visual_compatibility: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    platform_fit: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Voice
    tone_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    anti_patterns: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source examples
    example_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    source_influence_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Performance
    median_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    confidence_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    creator_diversity_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="provisional")
