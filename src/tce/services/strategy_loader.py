"""Loaders for strategy + repo portfolio + trend focus.

Two layers:

1. **Sync, file-based, lru-cached**: `load_strategy()`, `load_portfolio()`.
   Used by module-import-time consumers (copy_analyzer, copy_polisher) and
   anywhere a workspace_id isn't available. Reads `docs/*.md` from disk,
   one read per process.

2. **Async, workspace-aware**: `load_strategy_for_workspace(db, workspace_id)`,
   `load_portfolio_for_workspace(db, workspace_id)`,
   `load_trend_focus_for_workspace(db, workspace_id)`. Look up DB rows in
   `workspace_strategies` / `workspace_portfolios` / `workspace_trend_focus`
   first; if no row exists for the workspace (or workspace_id is None),
   fall back to the file-based default. Use these from agents that have
   a workspace_id in their context (weekly_planner, story_strategist,
   trend_scout, calendar regen endpoint).

This keeps existing single-tenant behavior identical while letting
multi-tenant runs override per workspace.
"""
from __future__ import annotations

import os
import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DOCS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "docs",
)
_STRATEGY_PATH = os.path.join(_DOCS_DIR, "super-coaching-strategy.md")
_PORTFOLIO_PATH = os.path.join(_DOCS_DIR, "repo-portfolio.md")

_MAX_CHARS = 12000
_PORTFOLIO_MAX_CHARS = 8000


# ---------------------------------------------------------------------------
# Sync, file-based defaults (the global "Ziv as tenant" behavior)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_strategy() -> str:
    """Return the global strategy doc, truncated. Empty string if missing."""
    try:
        with open(_STRATEGY_PATH, encoding="utf-8") as f:
            text = f.read()
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "\n\n[... strategy doc continues - key sections shown above]"
        return text
    except FileNotFoundError:
        return ""


@lru_cache(maxsize=1)
def load_portfolio() -> str:
    """Return the global repo portfolio, truncated. Empty string if missing."""
    try:
        with open(_PORTFOLIO_PATH, encoding="utf-8") as f:
            text = f.read()
        if len(text) > _PORTFOLIO_MAX_CHARS:
            text = (
                text[:_PORTFOLIO_MAX_CHARS]
                + "\n\n[... portfolio continues - flagship + recent repos shown above]"
            )
        return text
    except FileNotFoundError:
        return ""


# ---------------------------------------------------------------------------
# Async, workspace-aware (hybrid: DB row > file default)
# ---------------------------------------------------------------------------


async def load_strategy_for_workspace(
    db: AsyncSession | None, workspace_id: uuid.UUID | str | None
) -> str:
    """Strategy doc for this workspace, falling back to global file."""
    text = await _load_workspace_markdown(db, workspace_id, kind="strategy")
    if text is not None:
        # Truncate workspace overrides too so prompts stay manageable
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "\n\n[... strategy doc continues - workspace override truncated]"
        return text
    return load_strategy()


async def load_portfolio_for_workspace(
    db: AsyncSession | None, workspace_id: uuid.UUID | str | None
) -> str:
    """Portfolio doc for this workspace, falling back to global file."""
    text = await _load_workspace_markdown(db, workspace_id, kind="portfolio")
    if text is not None:
        if len(text) > _PORTFOLIO_MAX_CHARS:
            text = (
                text[:_PORTFOLIO_MAX_CHARS]
                + "\n\n[... portfolio continues - workspace override truncated]"
            )
        return text
    return load_portfolio()


async def load_trend_focus_for_workspace(
    db: AsyncSession | None, workspace_id: uuid.UUID | str | None
) -> dict[str, Any] | None:
    """Trend focus query overrides for this workspace, or None to use defaults.

    Returns a dict like {"source_queries": [...], "topical_queries": [...]}
    or None when the workspace has no override (caller should fall back to
    the hardcoded queries in trend_scout.py).
    """
    if not workspace_id or db is None:
        return None
    from tce.models.workspace_context import WorkspaceTrendFocus

    ws_uuid = _coerce_uuid(workspace_id)
    if ws_uuid is None:
        return None
    try:
        result = await db.execute(
            select(WorkspaceTrendFocus).where(WorkspaceTrendFocus.workspace_id == ws_uuid)
        )
        row = result.scalar_one_or_none()
        if row and isinstance(row.queries, dict):
            return row.queries
    except Exception:
        # DB unavailable / table missing - silently fall back
        return None
    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _load_workspace_markdown(
    db: AsyncSession | None, workspace_id: uuid.UUID | str | None, kind: str
) -> str | None:
    """Return workspace-specific markdown for the given kind, or None.

    `kind` is one of 'strategy' or 'portfolio'.
    """
    if not workspace_id or db is None:
        return None
    ws_uuid = _coerce_uuid(workspace_id)
    if ws_uuid is None:
        return None
    if kind == "strategy":
        from tce.models.workspace_context import WorkspaceStrategy as Model
    elif kind == "portfolio":
        from tce.models.workspace_context import WorkspacePortfolio as Model
    else:
        raise ValueError(f"Unknown workspace markdown kind: {kind}")
    try:
        result = await db.execute(select(Model).where(Model.workspace_id == ws_uuid))
        row = result.scalar_one_or_none()
        if row and row.markdown:
            return row.markdown
    except Exception:
        return None
    return None


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None
