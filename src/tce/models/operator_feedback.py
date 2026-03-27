"""OperatorFeedback model — structured rejection/edit categories (PRD Section 46)."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class OperatorFeedback(Base):
    __tablename__ = "operator_feedback"

    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("post_packages.id"), unique=True)

    # Taxonomy tags (PRD Section 46.2)
    feedback_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    feedback_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Action
    action_taken: Mapped[str] = mapped_column(String(20))  # approved/revised/rejected
    revision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Revised copy (operator's edited version of the posts)
    revised_facebook_post: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_linkedin_post: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Authorship
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    post_package: Mapped["PostPackage"] = relationship(  # noqa: F821
        back_populates="operator_feedback"
    )
