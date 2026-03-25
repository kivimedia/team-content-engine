"""LearningEvent model — post-performance tracking for the learning loop."""

import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class LearningEvent(Base):
    __tablename__ = "learning_events"

    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("post_packages.id"), unique=True)
    publish_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Actual metrics
    actual_comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_dms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_follows: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Analysis
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    postmortem_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_effectiveness_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    post_package: Mapped["PostPackage"] = relationship(  # noqa: F821
        back_populates="learning_event"
    )
