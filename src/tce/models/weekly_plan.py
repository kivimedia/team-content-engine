"""WeeklyPlan model - persists deep planning results across restarts."""

import uuid
from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"

    status: Mapped[str] = mapped_column(String(50), default="pending")
    plan_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    week_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
