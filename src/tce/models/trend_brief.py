"""TrendBrief model — daily/weekly trend scanning output (PRD Section 49)."""

from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class TrendBrief(Base):
    __tablename__ = "trend_briefs"

    date: Mapped[date] = mapped_column(Date)
    brief_type: Mapped[str] = mapped_column(String(20), default="daily")  # daily/weekly

    # Trends: list of trend objects per PRD Section 49.5
    trends: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    # Selections
    selected_trend_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    rejected_trend_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Operator input
    operator_additions: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    breaking_overrides: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
