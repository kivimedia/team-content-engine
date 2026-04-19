"""Shared loader for the Super Coaching strategy document.

Cached at import time so all agents share one read. Returns empty string if
the file is missing (safe fallback — agents degrade gracefully).
"""
from __future__ import annotations

import os
from functools import lru_cache

_STRATEGY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "docs",
    "super-coaching-strategy.md",
)

# Large enough to capture the full file including the voice rules appended at the end
_MAX_CHARS = 12000


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
