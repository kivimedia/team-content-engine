"""Lightweight asyncio-based scheduler for daily/weekly pipeline runs."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import Any

import structlog

logger = structlog.get_logger()


class ScheduledJob:
    """A recurring job definition."""

    def __init__(
        self,
        name: str,
        workflow: str,
        run_time: time,
        weekdays: list[int],
        context: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.workflow = workflow
        self.run_time = run_time
        self.weekdays = weekdays  # 0=Monday, 6=Sunday
        self.context = context or {}
        self.last_run: datetime | None = None
        self.next_run: datetime | None = None
        self._compute_next_run()

    def _compute_next_run(self) -> None:
        """Calculate the next run time."""
        now = datetime.now()
        today_run = datetime.combine(now.date(), self.run_time)

        # Check today first
        if now.weekday() in self.weekdays and now < today_run:
            self.next_run = today_run
            return

        # Find next valid weekday
        for days_ahead in range(1, 8):
            candidate = now + timedelta(days=days_ahead)
            if candidate.weekday() in self.weekdays:
                self.next_run = datetime.combine(candidate.date(), self.run_time)
                return

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "workflow": self.workflow,
            "run_time": self.run_time.isoformat(),
            "weekdays": self.weekdays,
            "last_run": (self.last_run.isoformat() if self.last_run else None),
            "next_run": (self.next_run.isoformat() if self.next_run else None),
        }


class Scheduler:
    """Manages recurring pipeline jobs."""

    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._setup_default_jobs()

    def _setup_default_jobs(self) -> None:
        """Configure default jobs per PRD Section 15."""
        self.jobs["daily_content"] = ScheduledJob(
            name="daily_content",
            workflow="daily_content",
            run_time=time(9, 0),
            weekdays=[0, 1, 2, 3, 4],  # Mon-Fri
        )
        self.jobs["weekly_planning"] = ScheduledJob(
            name="weekly_planning",
            workflow="weekly_planning",
            run_time=time(7, 0),
            weekdays=[0],  # Monday
        )
        self.jobs["weekly_learning"] = ScheduledJob(
            name="weekly_learning",
            workflow="weekly_learning",
            run_time=time(17, 0),
            weekdays=[4],  # Friday
        )
        # PRD Section 48.4: Quarterly corpus refresh nudge
        # Runs on the 1st of every 3rd month (Jan, Apr, Jul, Oct)
        self.jobs["quarterly_corpus_nudge"] = ScheduledJob(
            name="quarterly_corpus_nudge",
            workflow="notification_only",
            run_time=time(10, 0),
            weekdays=[0],  # Monday (closest to quarter start)
            context={
                "notification_type": "corpus_refresh_nudge",
                "message": (
                    "It's been 3 months since the last corpus addition. "
                    "Consider adding fresh examples to keep templates current."
                ),
            },
        )
        # GAP-03: LinkedIn comment polling (no webhook API, must poll)
        self.jobs["linkedin_comment_poll"] = ScheduledJob(
            name="linkedin_comment_poll",
            workflow="linkedin_poll",
            run_time=time(11, 0),  # 11 AM daily
            weekdays=[0, 1, 2, 3, 4],  # Mon-Fri
        )
        # GAP-06: Daily backup job
        self.jobs["daily_backup"] = ScheduledJob(
            name="daily_backup",
            workflow="backup",
            run_time=time(2, 0),  # 2 AM
            weekdays=[0, 1, 2, 3, 4, 5, 6],  # Every day
        )
        # Weekly repo spotlight - Sunday 07:00 Asia/Jerusalem.
        # Picks the tracked repo with the most recent commits this week
        # and runs the weekly_repo_spotlight workflow on it.
        # NOTE: scheduler uses server local time; on the VPS set TZ=Asia/Jerusalem
        # (or keep UTC and adjust run_time) for the correct trigger.
        self.jobs["weekly_repo_spotlight"] = ScheduledJob(
            name="weekly_repo_spotlight",
            workflow="weekly_repo_spotlight",
            run_time=time(7, 0),  # 07:00 local
            weekdays=[6],  # Sunday (0=Mon ... 6=Sun)
        )

    def start(self) -> None:
        """Start the scheduler background loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("scheduler.started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("scheduler.stopped")

    async def _loop(self) -> None:
        """Main scheduler loop — checks jobs every 60 seconds."""
        while self._running:
            now = datetime.now()
            for job in self.jobs.values():
                if (
                    job.next_run
                    and now >= job.next_run
                    and (job.last_run is None or job.last_run < job.next_run)
                ):
                    await self._execute_job(job)
            await asyncio.sleep(60)

    async def _execute_job(self, job: ScheduledJob) -> None:
        """Execute a scheduled job by running the appropriate workflow."""
        logger.info("scheduler.job_trigger", job=job.name, workflow=job.workflow)
        job.last_run = datetime.now()
        job._compute_next_run()

        # Handle special job types
        if job.workflow == "notification_only":
            # Just create a notification
            logger.info("scheduler.notification_job", message=job.context.get("message", ""))
            return

        if job.workflow == "backup":
            # Run backup
            from tce.services.backup import BackupService

            backup = BackupService(backup_dir="./backups")
            result = await backup.create_backup()
            logger.info("scheduler.backup_complete", result=result.get("status"))
            backup.cleanup_old_backups()
            return

        # GAP-03: LinkedIn comment polling for CTA keyword matching
        if job.workflow == "linkedin_poll":
            try:
                from tce.db.session import async_session
                from tce.services.cta_fulfillment import CTAFulfillmentService

                async with async_session() as db:
                    service = CTAFulfillmentService(db)
                    keywords = await service.get_active_keywords()
                    if keywords:
                        logger.info("scheduler.linkedin_poll", keyword_count=len(keywords))
                        # LinkedIn API doesn't expose public comment webhooks.
                        # Log active keywords for manual review or future API integration.
                        for kw in keywords:
                            logger.info("scheduler.linkedin_active_keyword", keyword=kw)
                    await db.commit()
            except Exception:
                logger.exception("scheduler.linkedin_poll_failed")
            return

        # GAP-12: For weekly learning, gather cost data AND feedback data
        if job.workflow == "weekly_learning":
            try:
                from tce.db.session import async_session
                from tce.services.cost_optimization import CostOptimizationService
                from tce.services.cost_tracker import CostTracker

                async with async_session() as db:
                    tracker = CostTracker(db)
                    daily = await tracker.get_daily_total()
                    monthly = await tracker.get_monthly_total()
                    cost_opt = CostOptimizationService(daily, monthly, 0.5)
                    cost_report = cost_opt.generate_weekly_cost_report(
                        {"total": daily * 7}  # approximate weekly total
                    )
                    job.context["cost_summary"] = cost_report
            except Exception:
                logger.exception("scheduler.cost_gathering_failed")

            # Gather weekly feedback, QA, and learning events
            try:
                from sqlalchemy import select

                from tce.db.session import async_session
                from tce.models.post_package import PostPackage
                from tce.services.learning import LearningService

                async with async_session() as db:
                    week_ago = datetime.now() - timedelta(days=7)
                    result = await db.execute(
                        select(PostPackage.id).where(
                            PostPackage.created_at >= week_ago
                        )
                    )
                    package_ids = [row[0] for row in result.all()]

                    if package_ids:
                        learning_svc = LearningService(db)
                        weekly_data = await learning_svc.get_weekly_data(package_ids)
                        job.context.update(weekly_data)
                        logger.info(
                            "scheduler.feedback_gathered",
                            packages=len(package_ids),
                            feedback=len(weekly_data.get("feedback_events", [])),
                            learning=len(weekly_data.get("learning_events", [])),
                            qa=len(weekly_data.get("qa_scorecards", [])),
                        )
                    else:
                        logger.info("scheduler.no_packages_this_week")
            except Exception:
                logger.exception("scheduler.feedback_gathering_failed")

        # Weekly repo spotlight: pick the hottest tracked repo and inject context
        if job.workflow == "weekly_repo_spotlight":
            try:
                from sqlalchemy import select

                from tce.db.session import async_session
                from tce.models.tracked_repo import TrackedRepo
                from tce.services.repo_service import RepoService

                async with async_session() as picker_db:
                    rows = (
                        await picker_db.execute(
                            select(TrackedRepo)
                            .where(TrackedRepo.is_archived.is_(False))
                            .order_by(
                                TrackedRepo.priority_score.desc(),
                                TrackedRepo.last_commit_at.desc().nulls_last(),
                            )
                            .limit(10)
                        )
                    ).scalars().all()

                if not rows:
                    logger.warning("scheduler.weekly_repo_spotlight.no_repos")
                    return

                # Fresh priority: latest remote HEAD changed in the last 7 days wins.
                # Fallback to first row (highest priority_score).
                service = RepoService()
                chosen = rows[0]
                for repo in rows:
                    sha = await service.remote_head_sha(repo)
                    if sha and sha != (repo.last_commit_sha or ""):
                        chosen = repo
                        break

                job.context.update(
                    {
                        "tracked_repo_id": str(chosen.id),
                        "angle": "new_features",
                        "_source": "repo",
                        "_source_angle": "new_features",
                    }
                )
                logger.info(
                    "scheduler.weekly_repo_spotlight.chosen",
                    repo=chosen.slug,
                )
            except Exception:
                logger.exception("scheduler.weekly_repo_spotlight.pick_failed")
                return

        # Run pipeline workflow
        try:
            from tce.db.session import async_session
            from tce.orchestrator.engine import PipelineOrchestrator
            from tce.orchestrator.workflows import WORKFLOWS
            from tce.settings import settings as app_settings

            steps = WORKFLOWS.get(job.workflow)
            if not steps:
                logger.error("scheduler.unknown_workflow", workflow=job.workflow)
                return

            async with async_session() as db:
                orchestrator = PipelineOrchestrator(steps=steps, db=db, settings=app_settings)
                result = await orchestrator.run(job.context)
                await db.commit()
                logger.info(
                    "scheduler.pipeline_complete",
                    job=job.name,
                    run_id=str(result.get("run_id")),
                )

                # Apply learning loop recommendations to DB
                if job.workflow == "weekly_learning":
                    await self._apply_learning_results(db, result)

        except Exception:
            logger.exception("scheduler.job_failed", job=job.name)

    async def _apply_learning_results(
        self, db: Any, pipeline_result: dict[str, Any]
    ) -> None:
        """Apply learning loop recommendations to templates and voice weights."""
        try:
            from tce.services.learning_updater import LearningUpdater

            recs = pipeline_result.get("weekly_recommendations", {})
            if not recs:
                logger.info("scheduler.no_learning_recommendations")
                return

            updater = LearningUpdater(db)

            # Apply template score updates
            template_recs = recs.get("template_recommendations", [])
            score_updates = [
                r for r in template_recs
                if isinstance(r, dict) and r.get("new_median_score") is not None
            ]
            if score_updates:
                applied = await updater.update_template_scores(score_updates)
                logger.info("scheduler.templates_updated", count=len(applied))

            # Apply voice weight adjustments
            voice_adj = recs.get("voice_weight_adjustments", {})
            if isinstance(voice_adj, dict) and voice_adj:
                applied = await updater.apply_voice_weight_adjustments(voice_adj)
                logger.info("scheduler.voice_weights_updated", count=len(applied))

            # Apply template status changes (promote/demote)
            for rec in template_recs:
                if isinstance(rec, dict) and rec.get("action") in ("promote", "demote"):
                    new_status = "recommended" if rec["action"] == "promote" else "provisional"
                    await updater.update_template_status(
                        rec.get("template_name", ""),
                        new_status,
                        rec.get("reason", ""),
                    )

            # Apply voice profile updates from drift analysis
            voice_updates = recs.get("voice_profile_updates", {})
            if isinstance(voice_updates, dict) and voice_updates:
                result = await updater.apply_voice_profile_updates(voice_updates)
                changes = result.get("changes", [])
                if changes:
                    logger.info("scheduler.voice_profile_updated", changes=changes)

            await db.commit()
            logger.info("scheduler.learning_applied", recommendations=recs.get("week_summary", ""))
        except Exception:
            logger.exception("scheduler.apply_learning_failed")

    async def trigger_job(self, job_name: str) -> dict[str, Any]:
        """Manually trigger a job."""
        if job_name not in self.jobs:
            return {"error": f"Job '{job_name}' not found"}

        job = self.jobs[job_name]
        await self._execute_job(job)
        return {"status": "triggered", "job": job.to_dict()}

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status and all job info."""
        return {
            "running": self._running,
            "jobs": {name: job.to_dict() for name, job in self.jobs.items()},
        }


# Singleton instance
scheduler = Scheduler()
