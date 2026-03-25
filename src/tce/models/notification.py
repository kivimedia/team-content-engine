"""Notification model — operator alerts (PRD Section 43.1)."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    # Type: package_ready, qa_failure, budget_alert, corpus_parsed,
    #       model_fallback, cta_pending, weekly_update, system_error
    notification_type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    message: Mapped[str] = mapped_column(Text)

    # Severity: info, warning, error, critical
    severity: Mapped[str] = mapped_column(String(20), default="info")

    # Channel: in_app, email, webhook
    channel: Mapped[str] = mapped_column(String(20), default="in_app")

    # Status
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Optional context data
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
