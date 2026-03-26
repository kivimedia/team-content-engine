"""DM Fulfillment Audit Trail (PRD Section 24.4).

Tracks what was promised via CTA and what was actually delivered.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class DMFulfillmentLog(Base):
    __tablename__ = "dm_fulfillment_logs"

    # Which package triggered this CTA
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("post_packages.id"), nullable=True
    )

    # What was promised
    cta_keyword: Mapped[str] = mapped_column(String(100))
    promised_asset: Mapped[str | None] = mapped_column(String(500), nullable=True)
    platform: Mapped[str] = mapped_column(String(20))  # facebook / linkedin

    # Who triggered it
    commenter_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # What was sent
    dm_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    dm_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_method: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # manual / automated / whatsapp

    # Fulfillment status
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending / sent / delivered / failed
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tracking
    whatsapp_joined: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)

    # Metadata
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
