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
                self.next_run = datetime.combine(
                    candidate.date(), self.run_time
                )
                return

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "workflow": self.workflow,
            "run_time": self.run_time.isoformat(),
            "weekdays": self.weekdays,
            "last_run": (
                self.last_run.isoformat() if self.last_run else None
            ),
            "next_run": (
                self.next_run.isoformat() if self.next_run else None
            ),
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
        """Execute a scheduled job."""
        logger.info("scheduler.job_trigger", job=job.name)
        job.last_run = datetime.now()
        job._compute_next_run()

        # Trigger the pipeline via the orchestrator
        # In production, this would create a DB session and run
        # the pipeline. For now, log that it would run.
        logger.info(
            "scheduler.job_would_run",
            job=job.name,
            workflow=job.workflow,
        )

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
            "jobs": {
                name: job.to_dict()
                for name, job in self.jobs.items()
            },
        }


# Singleton instance
scheduler = Scheduler()
