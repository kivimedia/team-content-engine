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


@router.get("/planning")
async def get_planning_costs(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get cost breakdown for weekly planning runs."""
    from sqlalchemy import func, select

    from tce.models.cost_event import CostEvent

    planning_agents = ["weekly_planner", "trend_scout"]
    result = await db.execute(
        select(
            CostEvent.run_id,
            func.sum(CostEvent.computed_cost_usd).label("total"),
            func.sum(CostEvent.input_tokens).label("input_tok"),
            func.sum(CostEvent.output_tokens).label("output_tok"),
            func.max(CostEvent.created_at).label("when"),
        )
        .where(CostEvent.agent_name.in_(planning_agents))
        .group_by(CostEvent.run_id)
        .order_by(func.max(CostEvent.created_at).desc())
        .limit(10)
    )
    runs = result.all()
    costs = [float(r[1]) for r in runs] if runs else []
    return {
        "plan_runs": len(runs),
        "avg_cost": round(sum(costs) / len(costs), 4) if costs else 0,
        "last_cost": round(costs[0], 4) if costs else 0,
        "total_planning_cost": round(sum(costs), 4),
        "runs": [
            {
                "run_id": str(r[0]),
                "cost_usd": round(float(r[1]), 4),
                "tokens": r[2] + r[3],
                "created_at": str(r[4]),
            }
            for r in runs
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


@router.get("/optimization-recommendations")
async def get_optimization_recommendations(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate cost optimization recommendations (PRD Section 36.6).

    Analyzes recent spending patterns and suggests concrete savings.
    """
    from datetime import timedelta

    from sqlalchemy import func, select

    from tce.models.cost_event import CostEvent
    from tce.services.cost_tracker import MODEL_PRICING

    since = date.today() - timedelta(days=days)

    # Get per-agent cost and model breakdown
    result = await db.execute(
        select(
            CostEvent.agent_name,
            CostEvent.model_used,
            func.sum(CostEvent.computed_cost_usd).label("cost"),
            func.sum(CostEvent.input_tokens).label("input_tok"),
            func.sum(CostEvent.output_tokens).label("output_tok"),
            func.avg(CostEvent.prompt_cache_hit_rate).label("avg_cache_rate"),
            func.count().label("calls"),
        )
        .where(CostEvent.date >= since)
        .group_by(CostEvent.agent_name, CostEvent.model_used)
        .order_by(func.sum(CostEvent.computed_cost_usd).desc())
    )
    rows = result.all()

    recommendations = []
    total_potential_savings = 0.0

    for row in rows:
        agent, model, cost, input_tok, output_tok, avg_cache, calls = row
        cost = float(cost)

        # Recommendation 1: Downgrade to cheaper model where possible
        if "opus" in model and agent not in ("story_strategist", "weekly_planner"):
            sonnet_pricing = MODEL_PRICING.get("claude-sonnet-4-20250514", {})
            opus_pricing = MODEL_PRICING.get(model, {})
            if opus_pricing and sonnet_pricing:
                current_cost = (
                    (input_tok / 1_000_000) * opus_pricing["input"]
                    + (output_tok / 1_000_000) * opus_pricing["output"]
                )
                cheaper_cost = (
                    (input_tok / 1_000_000) * sonnet_pricing["input"]
                    + (output_tok / 1_000_000) * sonnet_pricing["output"]
                )
                savings = current_cost - cheaper_cost
                if savings > 0.01:
                    total_potential_savings += savings
                    recommendations.append({
                        "type": "model_downgrade",
                        "agent": agent,
                        "current_model": model,
                        "suggested_model": "claude-sonnet-4-20250514",
                        "savings_usd": round(savings, 4),
                        "message": f"Switching {agent} from Opus to Sonnet saves ~${savings:.2f}/{days}d",
                    })

        # Recommendation 2: Low cache hit rate
        if avg_cache is not None and float(avg_cache) < 0.3 and cost > 0.10:
            est_savings = cost * 0.3  # ~30% savings from better caching
            total_potential_savings += est_savings
            recommendations.append({
                "type": "improve_caching",
                "agent": agent,
                "current_cache_rate": round(float(avg_cache), 4),
                "savings_usd": round(est_savings, 4),
                "message": (
                    f"{agent} has {float(avg_cache)*100:.0f}% cache hit rate. "
                    f"Improving to 60%+ could save ~${est_savings:.2f}/{days}d"
                ),
            })

        # Recommendation 3: Batch API for research_agent
        if agent == "research_agent" and calls >= 3:
            batch_savings = cost * 0.5  # 50% batch discount
            total_potential_savings += batch_savings
            recommendations.append({
                "type": "batch_api",
                "agent": agent,
                "calls": calls,
                "savings_usd": round(batch_savings, 4),
                "message": (
                    f"Research agent made {calls} calls. Using Batch API "
                    f"saves ~50% = ${batch_savings:.2f}/{days}d"
                ),
            })

    return {
        "period_days": days,
        "recommendations": recommendations,
        "total_potential_savings_usd": round(total_potential_savings, 4),
        "recommendation_count": len(recommendations),
    }
