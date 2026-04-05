"""MonthlyPlan model - container for 4-week content planning."""

from datetime import date

from sqlalchemy import Date, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class MonthlyPlan(Base):
    __tablename__ = "monthly_plans"

    month_start: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    # draft / planning / review / approved / generating / completed

    plan_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # monthly_theme, shared_trend_brief, etc.

    weekly_plan_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Array of 4 WeeklyPlan UUIDs
