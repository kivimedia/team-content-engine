"""Trend Scout specific endpoints - trigger scans and view results."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.settings import settings

router = APIRouter(prefix="/trends", tags=["trends"])

_scan_results: dict[str, dict[str, Any]] = {}


class TrendScanRequest(BaseModel):
    scan_type: str = "daily"
    focus_areas: list[str] = ["AI", "technology", "business automation"]
    operator_topics: list[str] = []


async def _run_trend_scan(scan_id: str, context: dict[str, Any], db: AsyncSession) -> None:
    """Run TrendScout agent in the background."""
    from tce.agents.registry import get_agent_class
    from tce.services.cost_tracker import CostTracker
    from tce.services.prompt_manager import PromptManager

    try:
        run_id = uuid.uuid4()
        cost_tracker = CostTracker(db)
        prompt_manager = PromptManager(db)
        agent_cls = get_agent_class("trend_scout")
        agent = agent_cls(
            db=db,
            settings=settings,
            cost_tracker=cost_tracker,
            prompt_manager=prompt_manager,
            run_id=run_id,
        )
        result = await agent.run(context)
        _scan_results[scan_id] = {
            "status": "completed",
            "result": result,
            "run_id": str(run_id),
        }
        await db.commit()
    except Exception as e:
        _scan_results[scan_id] = {"status": "failed", "error": str(e)}


@router.post("/scan")
async def trigger_trend_scan(
    request: TrendScanRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger an ad-hoc trend scan. Runs TrendScout agent."""
    from tce.db.session import async_session

    scan_id = str(uuid.uuid4())[:8]

    context = {
        "scan_type": request.scan_type,
        "focus_areas": request.focus_areas,
        "operator_topics": request.operator_topics,
    }

    # Run in background with its own DB session
    async def _background():
        async with async_session() as session:
            await _run_trend_scan(scan_id, context, session)

    asyncio.create_task(_background())

    return {
        "status": "scan_started",
        "scan_id": scan_id,
        "scan_type": request.scan_type,
        "focus_areas": request.focus_areas,
        "message": f"Trend scan running. Check GET /api/v1/trends/scan/{scan_id} for results.",
    }


@router.get("/scan/{scan_id}")
async def get_scan_result(scan_id: str) -> dict:
    """Get the result of a trend scan."""
    if scan_id in _scan_results:
        return _scan_results[scan_id]
    return {"status": "running", "scan_id": scan_id}
