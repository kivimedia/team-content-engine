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
                select(PatternTemplate).where(PatternTemplate.template_name == name)
            )
            template = result.scalar_one_or_none()
            if template:
                old_score = template.median_score
                template.median_score = new_score
                template.sample_size = (template.sample_size or 0) + 1
                applied.append(
                    {
                        "template_name": name,
                        "old_score": old_score,
                        "new_score": new_score,
                    }
                )

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
            select(PatternTemplate).where(PatternTemplate.template_name == template_name)
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
                select(CreatorProfile).where(CreatorProfile.creator_name == name)
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

    async def apply_voice_profile_updates(
        self,
        voice_drift: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply voice drift insights back to the FounderVoiceProfile.

        voice_drift: {
            add_taboos: [...],        # phrases operator always removes
            remove_taboos: [...],     # taboos that don't apply anymore
            add_themes: [...],        # new recurring themes from feedback
            add_values: [...],        # new values/beliefs detected
            add_phrases: [...],       # vocabulary phrases operator keeps using
            tone_adjustments: {axis: new_value},  # tone range tweaks
        }
        """
        from tce.models.founder_voice_profile import FounderVoiceProfile

        result = await self.db.execute(
            select(FounderVoiceProfile)
            .order_by(FounderVoiceProfile.created_at.desc())
            .limit(1)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            logger.warning("learning_updater.no_voice_profile")
            return {"status": "no_profile"}

        changes = []

        # Taboos
        if voice_drift.get("add_taboos"):
            current = list(profile.taboos or [])
            new_items = [t for t in voice_drift["add_taboos"] if t not in current]
            if new_items:
                profile.taboos = current + new_items
                changes.append(f"Added {len(new_items)} taboos")

        if voice_drift.get("remove_taboos"):
            current = list(profile.taboos or [])
            removed = [t for t in voice_drift["remove_taboos"] if t in current]
            if removed:
                profile.taboos = [t for t in current if t not in removed]
                changes.append(f"Removed {len(removed)} taboos")

        # Recurring themes
        if voice_drift.get("add_themes"):
            current = list(profile.recurring_themes or [])
            new_items = [t for t in voice_drift["add_themes"] if t not in current]
            if new_items:
                profile.recurring_themes = current + new_items
                changes.append(f"Added {len(new_items)} themes")

        # Values and beliefs
        if voice_drift.get("add_values"):
            current = list(profile.values_and_beliefs or [])
            new_items = [v for v in voice_drift["add_values"] if v not in current]
            if new_items:
                profile.values_and_beliefs = current + new_items
                changes.append(f"Added {len(new_items)} values")

        # Vocabulary phrases
        if voice_drift.get("add_phrases"):
            vocab = dict(profile.vocabulary_signature or {})
            current_phrases = list(vocab.get("phrases", []))
            new_items = [p for p in voice_drift["add_phrases"] if p not in current_phrases]
            if new_items:
                vocab["phrases"] = current_phrases + new_items
                profile.vocabulary_signature = vocab
                changes.append(f"Added {len(new_items)} phrases")

        # Tone range adjustments
        if voice_drift.get("tone_adjustments"):
            tone = dict(profile.tone_range or {})
            for axis, value in voice_drift["tone_adjustments"].items():
                if axis in tone:
                    old = tone[axis]
                    tone[axis] = max(1, min(10, value))
                    changes.append(f"Tone {axis}: {old} -> {tone[axis]}")
            profile.tone_range = tone

        if changes:
            await self.db.flush()
            desc = "; ".join(changes)
            await self._record_version_change("voice", f"Auto-updated from feedback: {desc}")
            logger.info("learning_updater.voice_profile_updated", changes=desc)

        return {"changes": changes}

    async def _record_version_change(
        self,
        change_type: str,
        description: str,
    ) -> None:
        """Record a version change in the system_versions table."""
        # Get current max versions
        result = await self.db.execute(
            select(SystemVersion).order_by(SystemVersion.created_at.desc()).limit(1)
        )
        latest = result.scalar_one_or_none()

        current_corpus = latest.corpus_version if latest else 1
        current_template = latest.template_library_version if latest else 1
        current_voice = latest.house_voice_version if latest else 1
        current_scoring = latest.scoring_config_version if latest else 1

        new_version = SystemVersion(
            corpus_version=(current_corpus + 1 if change_type == "corpus" else current_corpus),
            template_library_version=(
                current_template + 1 if change_type == "template" else current_template
            ),
            house_voice_version=(current_voice + 1 if change_type == "voice" else current_voice),
            scoring_config_version=(
                current_scoring + 1 if change_type == "scoring" else current_scoring
            ),
            change_type=change_type,
            change_description=description,
            changed_by="learning_loop",
        )
        self.db.add(new_version)
        await self.db.flush()
