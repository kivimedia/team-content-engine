"""WeeklyGuide model — shared weekly lead magnet (DOCX guide)."""

from datetime import date

from sqlalchemy import Date, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class WeeklyGuide(Base):
    __tablename__ = "weekly_guides"

    week_start_date: Mapped[date] = mapped_column(Date)
    weekly_theme: Mapped[str] = mapped_column(String(500))
    guide_title: Mapped[str] = mapped_column(String(500))

    # Files
    docx_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # CTA
    cta_keyword: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dm_flow: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fulfillment_link: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Metrics
    downloads_count: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Operator
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
