"""GuideOption model - multiple freebie/guide ideas per week."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class GuideOption(Base):
    __tablename__ = "guide_options"

    weekly_plan_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), index=True
    )
    option_index: Mapped[int] = mapped_column(Integer)  # 0, 1, 2
    title: Mapped[str] = mapped_column(String(500))
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sections: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_guide_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weekly_guides.id"), nullable=True
    )
