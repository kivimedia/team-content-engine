"""Shared loaders for strategy + repo portfolio documents.

Cached at import time so all agents share one read. Returns empty string if
the file is missing (safe fallback — agents degrade gracefully).
"""
from __future__ import annotations

import os
from functools import lru_cache

_DOCS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "docs",
)
_STRATEGY_PATH = os.path.join(_DOCS_DIR, "super-coaching-strategy.md")
_PORTFOLIO_PATH = os.path.join(_DOCS_DIR, "repo-portfolio.md")

# Large enough to capture the full file including the voice rules appended at the end
_MAX_CHARS = 12000
_PORTFOLIO_MAX_CHARS = 8000


@lru_cache(maxsize=1)
def load_strategy() -> str:
    """Return the strategy doc contents, truncated to _MAX_CHARS."""
    try:
        with open(_STRATEGY_PATH, encoding="utf-8") as f:
            text = f.read()
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "\n\n[... strategy doc continues — key sections shown above]"
        return text
    except FileNotFoundError:
        return ""


@lru_cache(maxsize=1)
def load_portfolio() -> str:
    """Return the repo portfolio contents, truncated to _PORTFOLIO_MAX_CHARS.

    Catalog of Ziv's actual builds with story angles - referenced by content
    agents so topics tie back to real, named work instead of generic AI news.
    """
    try:
        with open(_PORTFOLIO_PATH, encoding="utf-8") as f:
            text = f.read()
        if len(text) > _PORTFOLIO_MAX_CHARS:
            text = text[:_PORTFOLIO_MAX_CHARS] + "\n\n[... portfolio continues - flagship + recent repos shown above]"
        return text
    except FileNotFoundError:
        return ""
