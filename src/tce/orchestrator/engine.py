"""Pipeline orchestrator — DAG-based agent execution engine."""

from __future__ import annotations

import asyncio
import uuid
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from tce.agents.registry import get_agent_class
from tce.orchestrator.step import PipelineStep
from tce.services.cost_tracker import CostTracker
from tce.services.prompt_manager import PromptManager
from tce.settings import Settings

logger = structlog.get_logger()


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineOrchestrator:
    """Execute a DAG of agent steps with dependency resolution and concurrency."""

    def __init__(
        self,
        steps: list[PipelineStep],
        db: AsyncSession,
        settings: Settings,
        run_id: uuid.UUID | None = None,
    ) -> None:
        self.steps = {s.agent_name: s for s in steps}
        self.db = db
        self.settings = settings
        self.run_id = run_id or uuid.uuid4()
        self.context: dict[str, Any] = {}
        self.step_status: dict[str, StepStatus] = {
            s.agent_name: StepStatus.PENDING for s in steps
        }
        self.step_errors: dict[str, str] = {}
        self._cost_tracker = CostTracker(db)
        self._prompt_manager = PromptManager(db)

    async def run(self, initial_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute all pipeline steps respecting dependencies."""
        if initial_context:
            self.context.update(initial_context)

        self.context["run_id"] = str(self.run_id)
        logger.info("pipeline.start", run_id=str(self.run_id), steps=list(self.steps.keys()))

        while self._has_pending_steps():
            ready = self._get_ready_steps()
            if not ready:
                # No steps ready but some pending — deadlock or all blocked
                unfinished = [
                    name for name, status in self.step_status.items()
                    if status == StepStatus.PENDING
                ]
                logger.error("pipeline.deadlock", unfinished=unfinished)
                for name in unfinished:
                    self.step_status[name] = StepStatus.SKIPPED
                break

            # Run ready steps concurrently
            tasks = [self._run_step(name) for name in ready]
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "pipeline.complete",
            run_id=str(self.run_id),
            statuses={k: v.value for k, v in self.step_status.items()},
        )

        return {
            "run_id": str(self.run_id),
            "context": self.context,
            "step_status": {k: v.value for k, v in self.step_status.items()},
            "step_errors": self.step_errors,
        }

    async def _run_step(self, step_name: str) -> None:
        """Execute a single pipeline step."""
        step = self.steps[step_name]
        self.step_status[step_name] = StepStatus.RUNNING
        logger.info("step.start", step=step_name, run_id=str(self.run_id))

        try:
            agent_cls = get_agent_class(step_name)
            agent = agent_cls(
                db=self.db,
                settings=self.settings,
                cost_tracker=self._cost_tracker,
                prompt_manager=self._prompt_manager,
                run_id=self.run_id,
            )
            result = await asyncio.wait_for(
                agent.run(self.context),
                timeout=step.timeout_seconds,
            )
            self.context.update(result)
            self.step_status[step_name] = StepStatus.COMPLETED
            logger.info("step.complete", step=step_name)

        except Exception as e:
            logger.exception("step.failed", step=step_name, error=str(e))
            self.step_errors[step_name] = str(e)

            if step.optional:
                self.step_status[step_name] = StepStatus.SKIPPED
            else:
                self.step_status[step_name] = StepStatus.FAILED
                # Mark downstream steps as skipped
                self._skip_downstream(step_name)

    def _has_pending_steps(self) -> bool:
        return any(s == StepStatus.PENDING for s in self.step_status.values())

    def _get_ready_steps(self) -> list[str]:
        """Get steps whose dependencies are all completed."""
        ready = []
        for name, step in self.steps.items():
            if self.step_status[name] != StepStatus.PENDING:
                continue
            deps_met = all(
                self.step_status.get(dep) in (StepStatus.COMPLETED, StepStatus.SKIPPED)
                for dep in step.depends_on
            )
            # If any non-optional dep failed, skip this step
            any_dep_failed = any(
                self.step_status.get(dep) == StepStatus.FAILED
                for dep in step.depends_on
            )
            if any_dep_failed:
                self.step_status[name] = StepStatus.SKIPPED
                continue
            if deps_met:
                ready.append(name)
        return ready

    def _skip_downstream(self, failed_step: str) -> None:
        """Skip all steps that depend on a failed step."""
        for name, step in self.steps.items():
            if failed_step in step.depends_on and self.step_status[name] == StepStatus.PENDING:
                self.step_status[name] = StepStatus.SKIPPED
                self._skip_downstream(name)  # Cascade

    def get_status(self) -> dict[str, Any]:
        """Get current pipeline status."""
        return {
            "run_id": str(self.run_id),
            "step_status": {k: v.value for k, v in self.step_status.items()},
            "step_errors": self.step_errors,
        }
