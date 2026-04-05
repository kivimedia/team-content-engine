"""Operator control service (PRD Section 4.4).

Provides endpoints for:
- Locking/banning templates
- Approving/rejecting sources
- Editing influence weights per angle
- Disabling automation per platform
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.creator_profile import CreatorProfile
from tce.models.pattern_template import PatternTemplate
from tce.models.source_document import SourceDocument

logger = structlog.get_logger()

# Feature flags for platform automation
_platform_flags: dict[str, bool] = {
    "facebook": True,
    "linkedin": True,
}

# Engagement scorer weights (PRD 9.2)
_scorer_weights: dict[str, float] = {
    "shares": 3.0,
    "comments": 2.0,
    "saves": 2.5,
    "likes": 1.0,
    "clicks": 1.5,
    "dwell_time": 1.0,
}


class OperatorControlService:
    """Operator-level controls over the content engine."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- Template controls ---

    async def lock_template(self, template_name: str, reason: str = "") -> dict[str, Any] | None:
        """Lock a template (prevent it from being used)."""
        result = await self.db.execute(
            select(PatternTemplate).where(PatternTemplate.template_name == template_name)
        )
        template = result.scalar_one_or_none()
        if not template:
            return None

        old_status = template.status
        template.status = "locked"
        await self.db.flush()
        logger.info(
            "operator.template_locked",
            template=template_name,
            reason=reason,
        )
        return {
            "template_name": template_name,
            "old_status": old_status,
            "new_status": "locked",
            "reason": reason,
        }

    async def unlock_template(self, template_name: str) -> dict[str, Any] | None:
        """Unlock a previously locked template."""
        result = await self.db.execute(
            select(PatternTemplate).where(PatternTemplate.template_name == template_name)
        )
        template = result.scalar_one_or_none()
        if not template:
            return None

        template.status = "active"
        await self.db.flush()
        return {
            "template_name": template_name,
            "new_status": "active",
        }

    async def ban_template(self, template_name: str, reason: str = "") -> dict[str, Any] | None:
        """Permanently ban a template."""
        result = await self.db.execute(
            select(PatternTemplate).where(PatternTemplate.template_name == template_name)
        )
        template = result.scalar_one_or_none()
        if not template:
            return None

        template.status = "banned"
        await self.db.flush()
        logger.warning(
            "operator.template_banned",
            template=template_name,
            reason=reason,
        )
        return {
            "template_name": template_name,
            "new_status": "banned",
            "reason": reason,
        }

    # --- Source controls ---

    async def approve_source(self, document_id: str) -> dict[str, Any] | None:
        """Mark a source document as approved."""
        import uuid

        doc = await self.db.get(SourceDocument, uuid.UUID(document_id))
        if not doc:
            return None

        doc.notes = (doc.notes or "") + "\n[APPROVED by operator]"
        await self.db.flush()
        return {"document_id": document_id, "status": "approved"}

    async def reject_source(self, document_id: str, reason: str = "") -> dict[str, Any] | None:
        """Mark a source document as rejected."""
        import uuid

        doc = await self.db.get(SourceDocument, uuid.UUID(document_id))
        if not doc:
            return None

        doc.notes = (doc.notes or "") + f"\n[REJECTED by operator: {reason}]"
        await self.db.flush()
        return {
            "document_id": document_id,
            "status": "rejected",
            "reason": reason,
        }

    # --- Influence weight controls ---

    async def set_influence_weight(
        self,
        creator_name: str,
        weight: float,
    ) -> dict[str, Any] | None:
        """Set a creator's influence weight."""
        if weight < 0 or weight > 1.0:
            return {"error": "Weight must be between 0.0 and 1.0"}

        result = await self.db.execute(
            select(CreatorProfile).where(CreatorProfile.creator_name == creator_name)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return None

        old_weight = profile.allowed_influence_weight
        profile.allowed_influence_weight = weight
        await self.db.flush()

        return {
            "creator_name": creator_name,
            "old_weight": old_weight,
            "new_weight": weight,
        }

    # --- Engagement Scorer weight controls ---

    @staticmethod
    def get_scorer_weights() -> dict[str, Any]:
        """Get current engagement scorer weights."""
        return _scorer_weights.copy()

    @staticmethod
    def set_scorer_weights(weights: dict[str, float]) -> dict[str, Any]:
        """Update engagement scorer weights. Only updates provided keys."""
        updated = {}
        for key, value in weights.items():
            if key not in _scorer_weights:
                continue
            if not (0.0 <= value <= 10.0):
                return {"error": f"Weight '{key}' must be between 0.0 and 10.0"}
            old = _scorer_weights[key]
            _scorer_weights[key] = value
            updated[key] = {"old": old, "new": value}

        logger.info("operator.scorer_weights_updated", updated=updated)
        return {"updated": updated, "current": _scorer_weights.copy()}

    # --- Platform automation controls ---

    @staticmethod
    def get_platform_flags() -> dict[str, bool]:
        """Get current platform automation flags."""
        return _platform_flags.copy()

    @staticmethod
    def set_platform_flag(platform: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable automation for a platform."""
        if platform not in _platform_flags:
            return {"error": f"Unknown platform: {platform}"}

        old = _platform_flags[platform]
        _platform_flags[platform] = enabled
        logger.info(
            "operator.platform_flag",
            platform=platform,
            enabled=enabled,
        )
        return {
            "platform": platform,
            "old_value": old,
            "new_value": enabled,
        }
