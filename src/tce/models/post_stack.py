"""PostStackEntry model - curated publish-ready queue."""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class PostStackEntry(Base):
    __tablename__ = "post_stack"

    post_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("post_packages.id"), unique=True
    )
    position: Mapped[int] = mapped_column(Integer)  # sort order
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued / scheduled / published
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
