"""Feature flag service with DB persistence (PRD Section 24.3)."""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Default flags - these are seeded on first access
DEFAULT_FLAGS: dict[str, bool] = {
    "publish_facebook": False,
    "publish_linkedin": False,
    "auto_dm_facebook": False,
    "auto_dm_linkedin": False,
    "web_search_enabled": True,
    "image_generation_enabled": True,
    "scheduler_enabled": False,
}

# In-memory cache with TTL
_cache: dict[str, bool] = {}
_cache_ts: float = 0
CACHE_TTL = 60  # seconds


class FeatureFlagService:
    """DB-backed feature flags with in-memory caching."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load_all(self) -> dict[str, bool]:
        """Load all flags from DB, seeding defaults if needed."""
        global _cache, _cache_ts

        if _cache and (time.time() - _cache_ts) < CACHE_TTL:
            return _cache

        try:
            result = await self.db.execute(text("SELECT key, enabled FROM feature_flags"))
            rows = result.fetchall()
            flags = {row[0]: row[1] for row in rows}

            # Seed any missing defaults
            for key, default in DEFAULT_FLAGS.items():
                if key not in flags:
                    await self.db.execute(
                        text(
                            "INSERT INTO feature_flags (key, enabled) VALUES (:key, :enabled) "
                            "ON CONFLICT (key) DO NOTHING"
                        ),
                        {"key": key, "enabled": default},
                    )
                    flags[key] = default

            _cache = flags
            _cache_ts = time.time()
            return flags
        except Exception:
            logger.exception("feature_flags.load_failed")
            return dict(DEFAULT_FLAGS)

    async def is_enabled(self, key: str) -> bool:
        """Check if a feature flag is enabled."""
        flags = await self._load_all()
        return flags.get(key, DEFAULT_FLAGS.get(key, False))

    async def set_flag(self, key: str, enabled: bool) -> dict[str, Any]:
        """Set a feature flag value."""
        global _cache, _cache_ts
        await self.db.execute(
            text(
                "INSERT INTO feature_flags (key, enabled, updated_at) "
                "VALUES (:key, :enabled, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET enabled = :enabled, updated_at = NOW()"
            ),
            {"key": key, "enabled": enabled},
        )
        # Invalidate cache
        _cache_ts = 0
        return {"key": key, "enabled": enabled}

    async def get_all(self) -> dict[str, bool]:
        """Get all feature flags."""
        return await self._load_all()
