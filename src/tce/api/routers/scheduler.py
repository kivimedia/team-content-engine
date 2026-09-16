"""Scheduler control endpoints.

Recurring generation can spend (image generation, TTS, search quotas) and queues
subscription LLM jobs, so starting the scheduler, or running one of its jobs,
requires TCE_SCHEDULER_ENABLED=true. Status and stop are always available.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from tce.services.scheduler import scheduler
from tce.settings import settings

router = APIRouter(prefix="/scheduler", tags=["scheduler"])

_DISABLED_DETAIL = (
    "The scheduler is disabled (TCE_SCHEDULER_ENABLED is not true). Scheduled jobs can "
    "trigger paid services and queue LLM work, so they only run when an operator enables "
    "the scheduler in configuration and restarts TCE."
)


def _require_scheduler_enabled() -> None:
    if not settings.scheduler_enabled:
        raise HTTPException(status_code=409, detail=_DISABLED_DETAIL)


@router.get("/status")
async def get_scheduler_status() -> dict[str, Any]:
    """Get scheduler status and all configured jobs."""
    status = scheduler.get_status()
    status["enabled"] = bool(settings.scheduler_enabled)
    return status


@router.post("/trigger/{job_name}")
async def trigger_job(job_name: str) -> dict[str, Any]:
    """Manually trigger a scheduled job (only when the scheduler is enabled)."""
    _require_scheduler_enabled()
    return await scheduler.trigger_job(job_name)


@router.post("/start")
async def start_scheduler() -> dict:
    """Start the scheduler (refused with 409 unless TCE_SCHEDULER_ENABLED=true)."""
    _require_scheduler_enabled()
    scheduler.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_scheduler() -> dict:
    """Stop the scheduler."""
    scheduler.stop()
    return {"status": "stopped"}
