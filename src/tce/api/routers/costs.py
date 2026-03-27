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
        "budget_pct_used": (
            (total / float(settings.daily_budget_usd) * 100)
            if float(settings.daily_budget_usd) > 0
            else 0
        ),
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
        "budget_pct_used": (
            (total / float(settings.monthly_budget_usd) * 100)
            if float(settings.monthly_budget_usd) > 0
            else 0
        ),
    }


@router.get("/run/{run_id}", response_model=CostSummary)
async def get_run_costs(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    tracker = CostTracker(db)
    return await tracker.get_run_summary(run_id)


@router.get("/by-agent")
async def get_costs_by_agent(
    target_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get daily cost breakdown by agent."""
    from sqlalchemy import func, select

    from tce.models.cost_event import CostEvent

    target_date = target_date or date.today()
    result = await db.execute(
        select(
            CostEvent.agent_name,
            func.sum(CostEvent.computed_cost_usd).label("total"),
            func.sum(CostEvent.input_tokens).label("input_tokens"),
            func.sum(CostEvent.output_tokens).label("output_tokens"),
            func.count().label("call_count"),
        )
        .where(CostEvent.date == target_date)
        .group_by(CostEvent.agent_name)
        .order_by(func.sum(CostEvent.computed_cost_usd).desc())
    )
    rows = result.all()
    return {
        "date": str(target_date),
        "agents": [
            {
                "agent": r[0],
                "cost_usd": round(float(r[1]), 4),
                "input_tokens": r[2],
                "output_tokens": r[3],
                "call_count": r[4],
            }
            for r in rows
        ],
    }


@router.get("/model-distribution")
async def get_model_distribution(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get token usage distribution by model tier."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from tce.models.cost_event import CostEvent

    since = date.today() - timedelta(days=days)
    result = await db.execute(
        select(
            CostEvent.model_used,
            func.sum(CostEvent.input_tokens).label("input"),
            func.sum(CostEvent.output_tokens).label("output"),
            func.sum(CostEvent.computed_cost_usd).label("cost"),
            func.count().label("calls"),
        )
        .where(CostEvent.date >= since)
        .group_by(CostEvent.model_used)
    )
    rows = result.all()
    return {
        "period_days": days,
        "models": [
            {
                "model": r[0],
                "input_tokens": r[1],
                "output_tokens": r[2],
                "cost_usd": round(float(r[3]), 4),
                "call_count": r[4],
            }
            for r in rows
        ],
    }


@router.get("/cache-efficiency")
async def get_cache_efficiency(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get prompt cache hit rate trend."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from tce.models.cost_event import CostEvent

    since = date.today() - timedelta(days=days)
    result = await db.execute(
        select(
            CostEvent.date,
            func.avg(CostEvent.prompt_cache_hit_rate).label("avg_hit_rate"),
            func.sum(CostEvent.cache_read_tokens).label("cache_reads"),
            func.sum(CostEvent.cache_write_tokens).label("cache_writes"),
        )
        .where(CostEvent.date >= since, CostEvent.prompt_cache_hit_rate.isnot(None))
        .group_by(CostEvent.date)
        .order_by(CostEvent.date)
    )
    rows = result.all()
    return {
        "period_days": days,
        "daily": [
            {
                "date": str(r[0]),
                "avg_cache_hit_rate": round(float(r[1]), 4) if r[1] else 0,
                "cache_read_tokens": r[2] or 0,
                "cache_write_tokens": r[3] or 0,
            }
            for r in rows
        ],
    }


@router.get("/per-post")
async def get_cost_per_post(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get average cost per pipeline run (post package)."""
    from datetime import timedelta

    from sqlalchemy import func, select

    from tce.models.cost_event import CostEvent

    since = date.today() - timedelta(days=days)
    # Get unique run_ids and their total costs
    result = await db.execute(
        select(
            CostEvent.run_id,
            func.sum(CostEvent.computed_cost_usd).label("run_cost"),
        )
        .where(CostEvent.date >= since, CostEvent.run_id.isnot(None))
        .group_by(CostEvent.run_id)
    )
    runs = result.all()
    if not runs:
        return {"period_days": days, "total_runs": 0, "avg_cost_per_run": 0}

    costs = [float(r[1]) for r in runs]
    return {
        "period_days": days,
        "total_runs": len(runs),
        "avg_cost_per_run": round(sum(costs) / len(costs), 4),
        "min_cost": round(min(costs), 4),
        "max_cost": round(max(costs), 4),
        "total_cost": round(sum(costs), 4),
    }
