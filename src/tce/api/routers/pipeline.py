"""Pipeline execution endpoints — trigger, status, and cancel workflows."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.orchestrator.engine import PipelineOrchestrator
from tce.orchestrator.workflows import WORKFLOWS
from tce.settings import settings

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# In-memory store for active pipeline runs (replaced by a proper store in production)
_active_runs: dict[str, PipelineOrchestrator] = {}
_run_results: dict[str, dict[str, Any]] = {}


class PipelineRunRequest(BaseModel):
    workflow: str = "daily_content"
    context: dict[str, Any] = {}


class PipelineRunResponse(BaseModel):
    run_id: str
    workflow: str
    status: str


@router.post("/run", response_model=PipelineRunResponse)
async def trigger_pipeline(
    request: PipelineRunRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Trigger a pipeline workflow. Returns immediately with a run_id."""
    if request.workflow not in WORKFLOWS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown workflow: {request.workflow}. "
            f"Available: {list(WORKFLOWS.keys())}",
        )

    steps = WORKFLOWS[request.workflow]
    run_id = uuid.uuid4()
    orchestrator = PipelineOrchestrator(
        steps=steps,
        db=db,
        settings=settings,
        run_id=run_id,
    )
    _active_runs[str(run_id)] = orchestrator

    # Run in background
    async def _run() -> None:
        try:
            result = await orchestrator.run(request.context)
            _run_results[str(run_id)] = result
        except Exception as e:
            _run_results[str(run_id)] = {"error": str(e)}
        finally:
            _active_runs.pop(str(run_id), None)

    asyncio.create_task(_run())

    return {
        "run_id": str(run_id),
        "workflow": request.workflow,
        "status": "started",
    }


@router.get("/{run_id}/status")
async def get_pipeline_status(run_id: str) -> dict[str, Any]:
    """Get the current status of a pipeline run."""
    # Check active runs first
    if run_id in _active_runs:
        return _active_runs[run_id].get_status()

    # Check completed runs
    if run_id in _run_results:
        result = _run_results[run_id]
        return {
            "run_id": run_id,
            "status": "completed" if "error" not in result else "failed",
            **result,
        }

    raise HTTPException(status_code=404, detail="Pipeline run not found")


@router.get("/workflows")
async def list_workflows() -> dict[str, list[str]]:
    """List available workflow definitions."""
    return {
        name: [step.agent_name for step in steps]
        for name, steps in WORKFLOWS.items()
    }
