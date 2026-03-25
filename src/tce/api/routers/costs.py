"""Cost tracking and budget endpoints (PRD Section 36)."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.schemas.cost_event import CostSummary
from tce.services.cost_tracker import CostTracker
from tce.settings import settings

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/daily")
async def get_daily_costs(
    target_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tracker = CostTracker(db)
    total = await tracker.get_daily_total(target_date)
    return {
        "date": str(target_date or date.today()),
        "total_cost_usd": total,
        "daily_budget_usd": float(settings.daily_budget_usd),
        "budget_remaining_usd": float(settings.daily_budget_usd) - total,
        "budget_pct_used": (total / float(settings.daily_budget_usd) * 100) if float(settings.daily_budget_usd) > 0 else 0,
    }


@router.get("/monthly")
async def get_monthly_costs(
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tracker = CostTracker(db)
    total = await tracker.get_monthly_total(year, month)
    return {
        "total_cost_usd": total,
        "monthly_budget_usd": float(settings.monthly_budget_usd),
        "budget_remaining_usd": float(settings.monthly_budget_usd) - total,
        "budget_pct_used": (total / float(settings.monthly_budget_usd) * 100) if float(settings.monthly_budget_usd) > 0 else 0,
    }


@router.get("/run/{run_id}", response_model=CostSummary)
async def get_run_costs(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tracker = CostTracker(db)
    return await tracker.get_run_summary(run_id)
