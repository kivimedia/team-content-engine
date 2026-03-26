"""Scheduler control endpoints."""

from typing import Any

from fastapi import APIRouter

from tce.services.scheduler import scheduler

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status")
async def get_scheduler_status() -> dict[str, Any]:
    """Get scheduler status and all configured jobs."""
    return scheduler.get_status()


@router.post("/trigger/{job_name}")
async def trigger_job(job_name: str) -> dict[str, Any]:
    """Manually trigger a scheduled job."""
    return await scheduler.trigger_job(job_name)


@router.post("/start")
async def start_scheduler() -> dict:
    """Start the scheduler."""
    scheduler.start()
    return {"status": "started"}


@router.post("/stop")
async def stop_scheduler() -> dict:
    """Stop the scheduler."""
    scheduler.stop()
    return {"status": "stopped"}
