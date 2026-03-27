"""A/B Testing Framework (PRD Section 43.2).

Supports tagging PostPackages with experiments and comparing outcomes.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# PRD Section 43.2: Minimum sample size
DEFAULT_MIN_SAMPLE_SIZE = 10

# Supported experiment types
EXPERIMENT_TYPES = [
    "hook_variant",
    "cta_keyword",
    "visual_direction",
    "prompt_version",
    "template",
    "voice_weights",
]


class Experiment:
    """An A/B experiment definition."""

    def __init__(
        self,
        experiment_id: str,
        experiment_type: str,
        variants: list[str],
        min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    ) -> None:
        self.experiment_id = experiment_id
        self.experiment_type = experiment_type
        self.variants = variants
        self.min_sample_size = min_sample_size

    def assign_variant(self, day_number: int) -> str:
        """Deterministic assignment: odd days = A, even = B.

        PRD Section 43.2: assignment must be deterministic per run.
        """
        if len(self.variants) < 2:
            return self.variants[0] if self.variants else "control"
        return self.variants[day_number % len(self.variants)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "experiment_type": self.experiment_type,
            "variants": self.variants,
            "min_sample_size": self.min_sample_size,
        }


class ABTestingService:
    """Manages A/B experiments across PostPackages."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._experiments: dict[str, Experiment] = {}

    def create_experiment(
        self,
        experiment_type: str,
        variants: list[str] | None = None,
        min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    ) -> Experiment:
        """Create a new experiment."""
        exp_id = f"exp_{experiment_type}_{uuid.uuid4().hex[:8]}"
        variants = variants or ["A", "B"]
        experiment = Experiment(
            experiment_id=exp_id,
            experiment_type=experiment_type,
            variants=variants,
            min_sample_size=min_sample_size,
        )
        self._experiments[exp_id] = experiment
        logger.info(
            "ab_test.created",
            experiment_id=exp_id,
            type=experiment_type,
        )
        return experiment

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        return self._experiments.get(experiment_id)

    def list_experiments(self) -> list[dict[str, Any]]:
        return [exp.to_dict() for exp in self._experiments.values()]

    async def get_experiment_results(self, experiment_id: str) -> dict[str, Any]:
        """Compare outcomes between variants of an experiment.

        Looks at PostPackages tagged with this experiment_id
        and their corresponding LearningEvents.
        """
        # This would query PostPackages with experiment tags
        # For now, return structure for the learning loop to populate
        return {
            "experiment_id": experiment_id,
            "status": "collecting_data",
            "variants": {},
            "winner": None,
            "message": (
                "Experiment results will be available after "
                "enough posts are published with both variants."
            ),
        }
