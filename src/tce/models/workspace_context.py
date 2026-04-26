"""Per-workspace overrides for strategy / portfolio / trend focus.

These rows let a tenant supply their own context to the planner pipeline
instead of inheriting the global file-based defaults (Ziv's). The loaders
in `services/strategy_loader.py` look here first, fall back to file when
no row exists for the workspace.

One row per workspace per kind. Updated in place via PUT.
"""
from __future__ import annotations

import uuid

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tce.db.base import Base


class WorkspaceStrategy(Base):
    """Per-workspace business strategy markdown (overrides docs/super-coaching-strategy.md)."""

    __tablename__ = "workspace_strategies"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_strategies_workspace_id"),)

    markdown: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)


class WorkspacePortfolio(Base):
    """Per-workspace repo portfolio markdown (overrides docs/repo-portfolio.md)."""

    __tablename__ = "workspace_portfolios"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_portfolios_workspace_id"),)

    markdown: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Optional: GitHub org URL the portfolio was generated from (audit trail)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class WorkspaceTrendFocus(Base):
    """Per-workspace trend_scout query overrides.

    Replaces the hardcoded source_queries + topical_queries in trend_scout
    when present. Stored as JSONB so the structure can grow (e.g. per-niche
    sub-buckets) without migrations.

    Schema today: {"source_queries": [...], "topical_queries": [...]}
    """

    __tablename__ = "workspace_trend_focus"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_workspace_trend_focus_workspace_id"),)

    queries: Mapped[dict] = mapped_column(JSONB)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
