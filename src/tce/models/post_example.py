"""PostExample model — individual posts extracted from the corpus."""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class PostExample(Base):
    __tablename__ = "post_examples"

    # Foreign keys
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id"))
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("creator_profiles.id"))

    # Source info
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content
    post_text_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    hook_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body_structure: Mapped[str | None] = mapped_column(String(100), nullable=True)
    story_arc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tension_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visual_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visual_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_style: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Tags
    tone_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    topic_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    audience_guess: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Structure
    paragraph_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_bullets: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_explicit_keyword_cta: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Engagement
    visible_comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visible_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement_confidence: Mapped[str] = mapped_column(String(1), default="C")  # A/B/C
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_image_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Scoring
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Template linkage (set by enrichment pipeline)
    template_family: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Review
    manual_review_status: Mapped[str] = mapped_column(String(20), default="pending")
    parser_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    source_document: Mapped["SourceDocument"] = relationship(  # noqa: F821
        back_populates="post_examples"
    )
    creator: Mapped["CreatorProfile"] = relationship(  # noqa: F821
        back_populates="post_examples"
    )
