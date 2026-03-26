"""Learning loop DB updater — applies recommendations to templates and weights.

The LearningLoop agent generates recommendations. This service
actually writes the updates to the database (PRD Section 9.10).
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.pattern_template import PatternTemplate
from tce.models.system_version import SystemVersion

logger = structlog.get_logger()


class LearningUpdater:
    """Applies learning loop recommendations to the database."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def update_template_scores(
        self,
        template_updates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Update template median scores based on actual performance.

        Each update dict: {template_name, new_median_score, delta, reason}
        """
        applied = []
        for update in template_updates:
            name = update.get("template_name")
            new_score = update.get("new_median_score")
            if not name or new_score is None:
                continue

            result = await self.db.execute(
                select(PatternTemplate).where(
                    PatternTemplate.template_name == name
                )
            )
            template = result.scalar_one_or_none()
            if template:
                old_score = template.median_score
                template.median_score = new_score
                template.sample_size = (template.sample_size or 0) + 1
                applied.append({
                    "template_name": name,
                    "old_score": old_score,
                    "new_score": new_score,
                })

        if applied:
            await self.db.flush()
            await self._record_version_change(
                "template",
                f"Updated {len(applied)} template scores",
            )

        return applied

    async def update_template_status(
        self,
        template_name: str,
        new_status: str,
        reason: str = "",
    ) -> dict[str, Any] | None:
        """Promote or demote a template (provisional -> recommended, or downgrade)."""
        result = await self.db.execute(
            select(PatternTemplate).where(
                PatternTemplate.template_name == template_name
            )
        )
        template = result.scalar_one_or_none()
        if not template:
            return None

        old_status = template.status
        template.status = new_status
        await self.db.flush()

        await self._record_version_change(
            "template",
            f"{template_name}: {old_status} -> {new_status}. {reason}",
        )

        return {
            "template_name": template_name,
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
        }

    async def apply_voice_weight_adjustments(
        self,
        adjustments: dict[str, float],
    ) -> dict[str, Any]:
        """Apply suggested voice weight changes from the learning loop.

        adjustments: {creator_name: delta} e.g., {"Nathan Savis": -0.03, "Eden Bibas": 0.03}
        """
        from tce.models.creator_profile import CreatorProfile

        applied = {}
        for name, delta in adjustments.items():
            result = await self.db.execute(
                select(CreatorProfile).where(
                    CreatorProfile.creator_name == name
                )
            )
            profile = result.scalar_one_or_none()
            if profile:
                old_weight = profile.allowed_influence_weight
                new_weight = max(0.0, min(1.0, old_weight + delta))
                profile.allowed_influence_weight = new_weight
                applied[name] = {
                    "old_weight": old_weight,
                    "new_weight": round(new_weight, 4),
                    "delta": delta,
                }

        if applied:
            await self.db.flush()
            await self._record_version_change(
                "voice",
                f"Adjusted weights for {len(applied)} creators",
            )

        return applied

    async def _record_version_change(
        self,
        change_type: str,
        description: str,
    ) -> None:
        """Record a version change in the system_versions table."""
        # Get current max versions
        result = await self.db.execute(
            select(SystemVersion)
            .order_by(SystemVersion.created_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()

        current_corpus = latest.corpus_version if latest else 1
        current_template = latest.template_library_version if latest else 1
        current_voice = latest.house_voice_version if latest else 1
        current_scoring = latest.scoring_config_version if latest else 1

        new_version = SystemVersion(
            corpus_version=(
                current_corpus + 1 if change_type == "corpus" else current_corpus
            ),
            template_library_version=(
                current_template + 1 if change_type == "template" else current_template
            ),
            house_voice_version=(
                current_voice + 1 if change_type == "voice" else current_voice
            ),
            scoring_config_version=(
                current_scoring + 1 if change_type == "scoring" else current_scoring
            ),
            change_type=change_type,
            change_description=description,
            changed_by="learning_loop",
        )
        self.db.add(new_version)
        await self.db.flush()
