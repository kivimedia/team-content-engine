"""TrackedRepo model - a GitHub repo the team can cite or post about."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class TrackedRepo(Base):
    """A GitHub repo the team wants to generate content about or cite as example."""

    __tablename__ = "tracked_repos"

    repo_url: Mapped[str] = mapped_column(String(500))
    slug: Mapped[str] = mapped_column(String(200), index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)

    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # When true, posts whose topic overlaps this repo will cite it as example.
    include_examples_in_posts: Mapped[bool] = mapped_column(Boolean, default=True)
    # Topic substrings that should NEVER trigger this repo as example.
    blocked_topics: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # Free-form tags (domains, stacks) to aid matching.
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # Last observed state (updated by repo_scout).
    last_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Higher score = more likely to be auto-picked for weekly spotlight.
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    briefs: Mapped[list["RepoBrief"]] = relationship(  # noqa: F821
        back_populates="tracked_repo",
        cascade="all, delete-orphan",
    )
