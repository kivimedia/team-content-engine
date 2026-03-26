"""ContentCalendarEntry model — Mon-Fri content schedule (PRD Section 43.3)."""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class ContentCalendarEntry(Base):
    __tablename__ = "content_calendar"

    date: Mapped[date] = mapped_column(Date, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)  # 0=Mon, 4=Fri
    angle_type: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Links
    post_package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_packages.id"), nullable=True
    )
    weekly_guide_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weekly_guides.id"), nullable=True
    )

    # Status: planned / generating / ready / approved / published / skipped
    status: Mapped[str] = mapped_column(String(20), default="planned")
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Buffer posts (PRD Section 43.3): pre-approved backup posts
    is_buffer: Mapped[bool] = mapped_column(Boolean, default=False)
    buffer_priority: Mapped[int] = mapped_column(Integer, default=0)
