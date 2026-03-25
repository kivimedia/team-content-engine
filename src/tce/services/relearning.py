"""Corpus relearning workflow (PRD Section 48).

Handles three trigger types when new examples are uploaded:
- Trigger A: More examples from existing creators
- Trigger B: New creator added
- Trigger C: New template discovered

The system must get smarter over time, not just at launch.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.creator_profile import CreatorProfile
from tce.models.pattern_template import PatternTemplate
from tce.models.post_example import PostExample

logger = structlog.get_logger()

# PRD Section 16.2: Influence admission thresholds
MIN_EXAMPLES_FOR_ADMISSION = 5
MIN_CONFIDENCE_B_RATIO = 0.5  # At least 50% of examples must be B+ confidence
MAX_TEMPLATE_SCORE_DROP = 0.15  # 15% drop triggers review (PRD Section 48.6)
MAX_INFLUENCE_WEIGHT_DROP = 0.05  # PRD Section 48.6


class RelearningTrigger:
    """Detected trigger type from new corpus upload."""

    A = "more_examples_existing_creator"
    B = "new_creator"
    C = "new_template_discovered"


class RelearningService:
    """Manages corpus relearning when new examples are uploaded."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def detect_trigger(
        self, post_examples: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Analyze new examples to determine which trigger type applies."""
        if not post_examples:
            return {"trigger": None, "details": "No examples provided"}

        # Get existing creator names
        result = await self.db.execute(
            select(CreatorProfile.creator_name)
        )
        existing_creators = {
            row.lower() for row in result.scalars().all()
        }

        new_creator_names: set[str] = set()
        existing_creator_counts: dict[str, int] = {}

        for ex in post_examples:
            name = ex.get("creator_name", "unknown")
            if name.lower() in existing_creators:
                existing_creator_counts[name] = (
                    existing_creator_counts.get(name, 0) + 1
                )
            else:
                new_creator_names.add(name)

        triggers = []
        if existing_creator_counts:
            triggers.append(RelearningTrigger.A)
        if new_creator_names:
            triggers.append(RelearningTrigger.B)

        return {
            "triggers": triggers,
            "existing_creator_additions": existing_creator_counts,
            "new_creators": list(new_creator_names),
            "total_examples": len(post_examples),
        }

    async def evaluate_new_creator(
        self, creator_name: str, examples: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Evaluate whether a new creator should enter the influence pool.

        PRD Section 16.2: A new creator enters only if:
        - enough examples are parsed
        - enough examples have at least confidence B
        - the creator adds a genuinely distinct structural pattern
        """
        if len(examples) < MIN_EXAMPLES_FOR_ADMISSION:
            return {
                "admitted": False,
                "reason": (
                    f"Only {len(examples)} examples; "
                    f"need {MIN_EXAMPLES_FOR_ADMISSION}"
                ),
                "creator_name": creator_name,
            }

        # Check confidence distribution
        confidence_counts = {"A": 0, "B": 0, "C": 0}
        for ex in examples:
            conf = ex.get("engagement_confidence", "C")
            confidence_counts[conf] = (
                confidence_counts.get(conf, 0) + 1
            )

        b_plus_count = confidence_counts["A"] + confidence_counts["B"]
        b_plus_ratio = b_plus_count / len(examples)

        if b_plus_ratio < MIN_CONFIDENCE_B_RATIO:
            return {
                "admitted": False,
                "reason": (
                    f"Only {b_plus_ratio:.0%} examples at B+ confidence; "
                    f"need {MIN_CONFIDENCE_B_RATIO:.0%}"
                ),
                "creator_name": creator_name,
                "confidence_distribution": confidence_counts,
            }

        # Check for distinct patterns
        hook_types = {
            ex.get("hook_type")
            for ex in examples
            if ex.get("hook_type")
        }
        body_structures = {
            ex.get("body_structure")
            for ex in examples
            if ex.get("body_structure")
        }

        return {
            "admitted": True,
            "reason": "Meets all admission criteria",
            "creator_name": creator_name,
            "example_count": len(examples),
            "confidence_distribution": confidence_counts,
            "distinct_hook_types": list(hook_types),
            "distinct_body_structures": list(body_structures),
            "suggested_weight": 0.10,  # Start low for new creators
        }

    async def check_template_regression(
        self,
        template_id: uuid.UUID,
        old_score: float,
        new_score: float,
    ) -> dict[str, Any]:
        """Check if a template score dropped too much (PRD Section 48.6).

        If a template's pattern-level score drops by more than 15%,
        flag it for operator review before applying the change.
        """
        if old_score <= 0:
            return {"regression": False, "delta_pct": 0}

        delta_pct = (old_score - new_score) / old_score

        if delta_pct > MAX_TEMPLATE_SCORE_DROP:
            return {
                "regression": True,
                "template_id": str(template_id),
                "old_score": old_score,
                "new_score": new_score,
                "delta_pct": round(delta_pct, 3),
                "action": "requires_operator_review",
                "message": (
                    f"Template score dropped {delta_pct:.1%} "
                    f"(from {old_score:.1f} to {new_score:.1f}). "
                    "Review before applying."
                ),
            }

        return {
            "regression": False,
            "delta_pct": round(delta_pct, 3),
            "old_score": old_score,
            "new_score": new_score,
        }

    async def check_influence_weight_impact(
        self,
        new_creator_weight: float,
        existing_weights: dict[str, float],
    ) -> dict[str, Any]:
        """Check if adding a new creator would reduce any existing weight too much.

        PRD Section 48.6: If a new creator's admission would reduce any
        existing creator's influence weight by more than 0.05, flag it.
        """
        total_existing = sum(existing_weights.values())
        new_total = total_existing + new_creator_weight

        # Normalize weights
        scale_factor = 1.0 / new_total if new_total > 0 else 1.0
        impacts: dict[str, float] = {}
        flagged: list[str] = []

        for name, weight in existing_weights.items():
            new_weight = weight * scale_factor
            drop = weight - new_weight
            impacts[name] = round(drop, 4)
            if drop > MAX_INFLUENCE_WEIGHT_DROP:
                flagged.append(name)

        return {
            "flagged_creators": flagged,
            "weight_impacts": impacts,
            "requires_review": len(flagged) > 0,
        }

    async def get_relearning_summary(
        self, document_id: uuid.UUID
    ) -> dict[str, Any]:
        """Get a summary of what changed after a relearning cycle."""
        # Count examples for this document
        result = await self.db.execute(
            select(func.count())
            .select_from(PostExample)
            .where(PostExample.document_id == document_id)
        )
        example_count = result.scalar_one()

        # Count templates
        result = await self.db.execute(
            select(func.count()).select_from(PatternTemplate)
        )
        template_count = result.scalar_one()

        # Count creators
        result = await self.db.execute(
            select(func.count()).select_from(CreatorProfile)
        )
        creator_count = result.scalar_one()

        return {
            "document_id": str(document_id),
            "examples_from_document": example_count,
            "total_templates": template_count,
            "total_creators": creator_count,
        }
