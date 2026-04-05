"""SlotOption model - multiple topic options per calendar day slot."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class SlotOption(Base):
    __tablename__ = "slot_options"

    calendar_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_calendar.id"), index=True
    )
    option_index: Mapped[int] = mapped_column(Integer)  # 0, 1, 2
    topic: Mapped[str] = mapped_column(String(500))
    angle_type: Mapped[str] = mapped_column(String(100))
    plan_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # thesis, audience, belief_shift, evidence_requirements, etc.

    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    post_package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_packages.id"), nullable=True
    )
