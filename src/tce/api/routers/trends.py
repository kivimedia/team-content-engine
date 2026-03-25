"""Trend Scout specific endpoints — trigger scans and view results."""


from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db

router = APIRouter(prefix="/trends", tags=["trends"])


class TrendScanRequest(BaseModel):
    scan_type: str = "daily"
    focus_areas: list[str] = ["AI", "technology", "business automation"]
    operator_topics: list[str] = []


@router.post("/scan")
async def trigger_trend_scan(
    request: TrendScanRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trigger an ad-hoc trend scan. Returns immediately; results appear in /briefs/trends."""
    # In production, this would trigger the trend_scout agent via the pipeline
    return {
        "status": "scan_queued",
        "scan_type": request.scan_type,
        "focus_areas": request.focus_areas,
        "message": "Trend scan has been queued. Check /api/v1/briefs/trends for results.",
    }
