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

3. **Effective strategy with provenance**: `load_effective_strategy(db, workspace_id)`
   returns the text agents should apply plus where each part came from. The public
   default file carries the settled positioning; a workspace DB override extends it
   with (private) business context. An override whose markdown starts with
   `<!-- tce-strategy: replace -->` replaces the default instead. Editorial agents
   (selector, packets, weekly planner) use this path.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
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
_VOICE_MARKER = "## ZIV'S VOICE AND WRITING STYLE"
REPLACE_MARKER = "<!-- tce-strategy: replace -->"


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
def load_voice_patterns() -> str:
    """Return the full ZIV'S VOICE section of the strategy doc.

    The voice section sits well past the 12k char cutoff for load_strategy(),
    so writers/critics that need ALL 36 patterns + banned vocab + meta-rule
    must load it via this dedicated path instead of relying on the truncated
    strategy text. Empty string if the section heading isn't found.
    """
    try:
        with open(_STRATEGY_PATH, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return ""
    marker = _VOICE_MARKER
    start = text.find(marker)
    if start == -1:
        return ""
    # Voice section runs to EOF in the current doc; if a later top-level
    # section is added, stop at the next "\n## " that is not the voice one.
    rest = text[start:]
    next_section = rest.find("\n## ", len(marker))
    if next_section != -1:
        return rest[:next_section].strip()
    return rest.strip()


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
            text = (
                text[:_MAX_CHARS]
                + "\n\n[... strategy doc continues - workspace override truncated]"
            )
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
# Effective strategy with provenance (editorial path)
# ---------------------------------------------------------------------------


@dataclass
class EffectiveStrategy:
    """Strategy text an agent should apply, and where every part of it came from."""

    text: str
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "sources": list(self.sources)}


def _read_default_file() -> str:
    try:
        with open(_STRATEGY_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _positioning_only(text: str) -> str:
    """The default doc without the voice section (writers load that separately)."""
    idx = text.find(_VOICE_MARKER)
    if idx == -1:
        return text.strip()
    return text[:idx].rstrip().rstrip("-").rstrip()


async def load_effective_strategy(
    db: AsyncSession | None,
    workspace_id: uuid.UUID | str | None,
    *,
    include_voice: bool = False,
) -> EffectiveStrategy:
    """Default public strategy, extended (or replaced) by the workspace DB override.

    Provenance entries: {"kind": "file"|"db_override", "ref", "mode", "chars", ...}.
    A DB error is recorded in provenance as {"kind": "db_override", "status": "error"}
    rather than silently looking like "no override".
    """
    sources: list[dict[str, Any]] = []
    default_raw = _read_default_file()
    default_text = default_raw.strip() if include_voice else _positioning_only(default_raw)

    override_row = None
    ws_uuid = _coerce_uuid(workspace_id) if workspace_id else None
    if db is not None and ws_uuid is not None:
        from tce.models.workspace_context import WorkspaceStrategy

        try:
            result = await db.execute(
                select(WorkspaceStrategy).where(WorkspaceStrategy.workspace_id == ws_uuid)
            )
            override_row = result.scalar_one_or_none()
        except Exception as exc:  # table missing / DB down: say so in provenance
            sources.append(
                {
                    "kind": "db_override",
                    "ref": "workspace_strategies",
                    "status": "error",
                    "detail": type(exc).__name__,
                }
            )

    override_text = (override_row.markdown or "").strip() if override_row else ""
    replace = override_text.startswith(REPLACE_MARKER)

    parts: list[str] = []
    if default_text and not replace:
        parts.append(default_text)
        sources.append(
            {
                "kind": "file",
                "ref": "docs/super-coaching-strategy.md",
                "mode": "default",
                "chars": len(default_text),
                "includes_voice": include_voice,
            }
        )
    if override_text:
        body = override_text[len(REPLACE_MARKER):].strip() if replace else override_text
        if len(body) > _MAX_CHARS:
            body = body[:_MAX_CHARS] + "\n\n[... workspace strategy override truncated]"
        if replace:
            parts.append(body)
        else:
            parts.append(
                "WORKSPACE CONTEXT (adds business context for this workspace; the settled "
                "positioning above - audience, offer, strategy-session CTA, no prices - "
                "stays binding where they conflict):\n\n" + body
            )
        sources.append(
            {
                "kind": "db_override",
                "ref": "workspace_strategies",
                "mode": "replace" if replace else "extend",
                "label": override_row.label,
                "row_id": str(override_row.id),
                "updated_at": override_row.updated_at.isoformat()
                if getattr(override_row, "updated_at", None)
                else None,
                "chars": len(body),
            }
        )
    return EffectiveStrategy(text="\n\n".join(parts), sources=sources)


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
