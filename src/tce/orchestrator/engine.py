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
from tce.services.pipeline_saver import PipelineResultSaver
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
        self.step_logs: dict[str, list[str]] = {
            s.agent_name: [] for s in steps
        }
        self._cost_tracker = CostTracker(db)
        self._prompt_manager = PromptManager(db)
        self._saver = PipelineResultSaver(db, self.run_id)

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
        """Execute a single pipeline step with retry logic."""
        step = self.steps[step_name]
        self.step_status[step_name] = StepStatus.RUNNING
        logger.info("step.start", step=step_name, run_id=str(self.run_id))

        last_error = None
        for attempt in range(1, step.max_retries + 1):
            try:
                agent_cls = get_agent_class(step_name)
                log_list = self.step_logs[step_name]
                if attempt > 1:
                    import datetime
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    log_list.append(f"[{ts}] Retry attempt {attempt}/{step.max_retries}...")
                    logger.info("step.retry", step=step_name, attempt=attempt, max=step.max_retries)

                agent = agent_cls(
                    db=self.db,
                    settings=self.settings,
                    cost_tracker=self._cost_tracker,
                    prompt_manager=self._prompt_manager,
                    run_id=self.run_id,
                    progress_log=log_list,
                )
                result = await asyncio.wait_for(
                    agent.run(self.context),
                    timeout=step.timeout_seconds,
                )
                self.context.update(result)
                await self._persist_step_result(step_name)
                # Commit after each step so data survives process restarts
                await self.db.commit()
                self.step_status[step_name] = StepStatus.COMPLETED
                logger.info("step.complete", step=step_name, attempt=attempt)
                return  # Success - exit retry loop

            except Exception as e:
                import traceback
                err_msg = str(e) or f"{type(e).__name__}: {repr(e)}"
                tb = traceback.format_exc()
                last_error = err_msg
                logger.warning(
                    "step.attempt_failed",
                    step=step_name,
                    attempt=attempt,
                    max_retries=step.max_retries,
                    error=err_msg,
                )
                try:
                    await self.db.rollback()
                except Exception:
                    pass

                if attempt < step.max_retries:
                    # Wait before retrying (5s, 10s exponential)
                    wait_secs = 5 * attempt
                    log_list = self.step_logs[step_name]
                    import datetime
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    log_list.append(f"[{ts}] Step failed: {err_msg[:120]}. Retrying in {wait_secs}s...")
                    await asyncio.sleep(wait_secs)

        # All retries exhausted
        logger.exception("step.failed", step=step_name, error=last_error, attempts=step.max_retries)
        self.step_errors[step_name] = last_error or "Unknown error"

        if step.optional:
            self.step_status[step_name] = StepStatus.SKIPPED
        else:
            self.step_status[step_name] = StepStatus.FAILED
            # Mark downstream steps as skipped
            self._skip_downstream(step_name)

    async def _persist_step_result(self, step_name: str) -> None:
        """Persist agent output to the database after a step completes."""
        try:
            if step_name == "corpus_analyst":
                ids = await self._saver.save_post_examples(
                    self.context
                )
                self.context["_post_example_ids"] = [
                    str(i) for i in ids
                ]
            elif step_name == "engagement_scorer":
                await self._saver.save_engagement_scores(
                    self.context
                )
            elif step_name == "pattern_miner":
                ids = await self._saver.save_templates(self.context)
                self.context["_template_ids"] = [
                    str(i) for i in ids
                ]
            elif step_name == "trend_scout":
                tid = await self._saver.save_trend_brief(
                    self.context
                )
                if tid:
                    self.context["_trend_brief_id"] = tid
            elif step_name == "story_strategist":
                sid = await self._saver.save_story_brief(
                    self.context
                )
                if sid:
                    self.context["_story_brief_id"] = sid
            elif step_name == "research_agent":
                rid = await self._saver.save_research_brief(
                    self.context
                )
                if rid:
                    self.context["_research_brief_id"] = rid
            elif step_name == "qa_agent":
                qid = await self._saver.save_qa_scorecard(
                    self.context
                )
                if qid:
                    self.context["_qa_scorecard_id"] = qid
            elif step_name == "creative_director":
                # After creative_director, we have all pieces
                # for the PostPackage — assemble and save
                pid = await self._saver.save_post_package(
                    self.context
                )
                if pid:
                    self.context["_post_package_id"] = pid
                    # Link package to calendar entry and update status
                    await self._link_package_to_calendar(pid)

                # Generate actual images from creative director prompts
                image_prompts = self.context.get("image_prompts", [])
                if image_prompts and self.settings.fal_api_key:
                    log_list = self.step_logs.get("creative_director", [])
                    import datetime
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    log_list.append(f"[{ts}] Generating {len(image_prompts)} images via fal.ai...")
                    try:
                        from tce.services.image_generation import ImageGenerationService
                        img_svc = ImageGenerationService(self.settings.fal_api_key)
                        generated = await img_svc.generate_batch(image_prompts)
                        self.context["generated_images"] = generated
                        success = sum(1 for g in generated if g.get("status") == "generated")
                        ts2 = datetime.datetime.now().strftime("%H:%M:%S")
                        log_list.append(f"[{ts2}] {success}/{len(image_prompts)} images generated")
                    except Exception as img_err:
                        ts2 = datetime.datetime.now().strftime("%H:%M:%S")
                        log_list.append(f"[{ts2}] Image generation failed: {str(img_err)[:80]}")
                        logger.exception("image_gen.batch_failed")
            elif step_name == "docx_guide_builder":
                gid = await self._saver.save_weekly_guide(
                    self.context
                )
                if gid:
                    self.context["_weekly_guide_id"] = gid
        except Exception:
            logger.exception(
                "saver.error",
                step=step_name,
                run_id=str(self.run_id),
            )
            # Persistence errors are logged but don't fail the step

    async def _link_package_to_calendar(self, package_id: uuid.UUID) -> None:
        """Link a generated package to today's calendar entry and mark it ready."""
        from datetime import date as date_type

        from sqlalchemy import select

        from tce.models.content_calendar import ContentCalendarEntry

        day_of_week = self.context.get("day_of_week")
        today = date_type.today()
        try:
            entry = None
            if day_of_week is not None:
                stmt = select(ContentCalendarEntry).where(
                    ContentCalendarEntry.day_of_week == day_of_week,
                    ContentCalendarEntry.status.in_(["planned", "generating"]),
                ).order_by(ContentCalendarEntry.date.desc()).limit(1)
                result = await self.db.execute(stmt)
                entry = result.scalar_one_or_none()
            if not entry:
                stmt2 = select(ContentCalendarEntry).where(
                    ContentCalendarEntry.date == today,
                ).limit(1)
                result2 = await self.db.execute(stmt2)
                entry = result2.scalar_one_or_none()
            if entry:
                entry.post_package_id = package_id
                entry.status = "ready"
                await self.db.flush()
                logger.info("calendar.linked", entry_id=str(entry.id), package_id=str(package_id))
        except Exception:
            logger.exception("calendar.link_failed", package_id=str(package_id))

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
            "step_logs": {k: v[-20:] for k, v in self.step_logs.items()},
        }
