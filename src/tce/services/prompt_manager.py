"""Prompt versioning service — CRUD and resolution for PromptVersion (PRD Section 39)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.prompt_version import PromptVersion


class PromptManager:
    """Manage versioned prompts for each agent."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active(self, agent_name: str) -> PromptVersion | None:
        """Get the currently active prompt version for an agent."""
        result = await self.db.execute(
            select(PromptVersion)
            .where(PromptVersion.agent_name == agent_name, PromptVersion.is_active.is_(True))
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_version(
        self,
        agent_name: str,
        prompt_text: str,
        variables: list[str] | None = None,
        model_target: str | None = None,
        created_by: str | None = None,
    ) -> PromptVersion:
        """Create a new prompt version and retire the previous one."""
        # Get current max version
        result = await self.db.execute(
            select(PromptVersion.version)
            .where(PromptVersion.agent_name == agent_name)
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        current_max = result.scalar_one_or_none() or 0

        # Retire all active versions for this agent
        active_result = await self.db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.is_active.is_(True),
            )
        )
        for old in active_result.scalars().all():
            old.is_active = False
            old.status = "retired"

        # Create new version
        new_version = PromptVersion(
            agent_name=agent_name,
            version=current_max + 1,
            prompt_text=prompt_text,
            variables=variables,
            model_target=model_target,
            is_active=True,
            status="active",
            created_by=created_by,
        )
        self.db.add(new_version)
        await self.db.flush()
        return new_version

    async def rollback(self, agent_name: str, target_version: int) -> PromptVersion | None:
        """Roll back to a specific version."""
        # Retire current active
        active_result = await self.db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.is_active.is_(True),
            )
        )
        for old in active_result.scalars().all():
            old.is_active = False
            old.status = "retired"

        # Activate target version
        result = await self.db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == agent_name,
                PromptVersion.version == target_version,
            )
        )
        target = result.scalar_one_or_none()
        if target:
            target.is_active = True
            target.status = "active"
            await self.db.flush()
        return target

    async def list_versions(self, agent_name: str) -> list[PromptVersion]:
        """List all prompt versions for an agent."""
        result = await self.db.execute(
            select(PromptVersion)
            .where(PromptVersion.agent_name == agent_name)
            .order_by(PromptVersion.version.desc())
        )
        return list(result.scalars().all())

    async def check_quality_regression(
        self,
        agent_name: str,
        recent_qa_scores: list[float],
        threshold: float = 6.5,
        min_failures: int = 3,
    ) -> dict | None:
        """Check if a prompt version is causing quality regression (PRD Section 39.5).

        If the recent QA composite scores drop below threshold for min_failures
        consecutive runs, flag the active prompt for rollback.

        Returns rollback recommendation dict or None.
        """
        import structlog

        logger = structlog.get_logger()

        if len(recent_qa_scores) < min_failures:
            return None

        # Check last N scores
        recent = recent_qa_scores[-min_failures:]
        failures = sum(1 for s in recent if s < threshold)

        if failures >= min_failures:
            active = await self.get_active(agent_name)
            if not active or active.version <= 1:
                return None  # No previous version to rollback to

            logger.warning(
                "prompt.quality_regression",
                agent=agent_name,
                version=active.version,
                recent_scores=recent,
                threshold=threshold,
            )

            # Update performance notes on current version
            active.performance_notes = (
                f"Quality regression detected: {failures}/{min_failures} "
                f"scores below {threshold}. Recent: {recent}. "
                f"Auto-flagged for rollback review."
            )
            await self.db.flush()

            return {
                "agent_name": agent_name,
                "current_version": active.version,
                "recommended_rollback_to": active.version - 1,
                "recent_scores": recent,
                "threshold": threshold,
                "message": (
                    f"{agent_name} prompt v{active.version} has {failures} consecutive "
                    f"QA failures (below {threshold}). Consider rolling back to v{active.version - 1}."
                ),
            }

        return None
