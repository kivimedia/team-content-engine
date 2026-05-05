"""CompetitorPostSnapshot — periodic poll-time snapshot of a competitor's post.

CompetitorVelocityService writes one row per (post_id, captured_at). The
delta_views_per_hour column is precomputed at insert vs. the most recent
prior snapshot of the same post, so trend_scout can sort cheaply without
joining back across snapshots.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class CompetitorPostSnapshot(Base):
    __tablename__ = "competitor_post_snapshots"

    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("creator_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    post_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    post_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Computed at insert vs. the most recent prior snapshot of the same post.
    # Null on the very first snapshot of a post.
    delta_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delta_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_views_per_hour: Mapped[float | None] = mapped_column(Float, nullable=True)
