"""RepoBrief model - cached analysis of a repo at a specific commit for a specific angle."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tce.db.base import Base


class RepoBrief(Base):
    """An angle-specific summary of a tracked repo at a given commit.

    Caching contract: a brief is reused only while its `commit_sha` matches the
    current HEAD on the default branch AND it is within the TTL (default 6 hours).
    Otherwise the repo_scout regenerates it.
    """

    __tablename__ = "repo_briefs"

    tracked_repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracked_repos.id", ondelete="CASCADE")
    )

    # new_features | whole_repo | recent_fixes | generic
    angle: Mapped[str] = mapped_column(String(30))
    commit_sha: Mapped[str] = mapped_column(String(40))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Narrative fields
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    architecture_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    readme_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured JSON payloads from repo_scout
    recent_commits: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    feature_highlights: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    bug_fixes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    code_snippets: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    package_hints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    tracked_repo: Mapped["TrackedRepo"] = relationship(  # noqa: F821
        back_populates="briefs"
    )
