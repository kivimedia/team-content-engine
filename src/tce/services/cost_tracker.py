"""Cost tracking service — records and queries per-agent LLM costs (PRD Section 36)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.cost_event import CostEvent

# Token pricing per model (per million tokens, March 2026 estimates)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-20250514": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,  # 0.1x input
        "cache_write": 18.75,  # 1.25x input
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
}


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Compute USD cost from token counts."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-20250514"])
    cost = (
        (input_tokens / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"]
        + (cache_read_tokens / 1_000_000) * pricing["cache_read"]
        + (cache_write_tokens / 1_000_000) * pricing["cache_write"]
    )
    return round(cost, 6)


class CostTracker:
    """Records cost events and provides budget queries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        run_id: uuid.UUID,
        agent_name: str,
        model_used: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        wall_time_seconds: float | None = None,
        prompt_id: uuid.UUID | None = None,
    ) -> CostEvent:
        """Record a single cost event."""
        cost_usd = compute_cost(
            model_used, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
        )

        # Compute cache hit rate
        total_input = input_tokens + cache_read_tokens + cache_write_tokens
        cache_hit_rate = (cache_read_tokens / total_input) if total_input > 0 else None

        event = CostEvent(
            run_id=run_id,
            date=date.today(),
            agent_name=agent_name,
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            computed_cost_usd=cost_usd,
            wall_time_seconds=wall_time_seconds,
            prompt_cache_hit_rate=cache_hit_rate,
            prompt_id=prompt_id,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def get_daily_total(self, target_date: date | None = None) -> float:
        """Get total cost for a given day."""
        target_date = target_date or date.today()
        result = await self.db.execute(
            select(func.coalesce(func.sum(CostEvent.computed_cost_usd), 0.0)).where(
                CostEvent.date == target_date
            )
        )
        return float(result.scalar_one())

    async def get_monthly_total(self, year: int | None = None, month: int | None = None) -> float:
        """Get total cost for a given month."""
        today = date.today()
        year = year or today.year
        month = month or today.month
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)

        result = await self.db.execute(
            select(func.coalesce(func.sum(CostEvent.computed_cost_usd), 0.0)).where(
                CostEvent.date >= start,
                CostEvent.date < end,
            )
        )
        return float(result.scalar_one())

    async def get_run_summary(self, run_id: uuid.UUID) -> dict[str, Any]:
        """Get cost summary for a specific pipeline run."""
        events = await self.db.execute(select(CostEvent).where(CostEvent.run_id == run_id))
        rows = events.scalars().all()

        by_agent: dict[str, float] = {}
        by_model: dict[str, float] = {}
        total = 0.0
        total_input = 0
        total_output = 0
        cache_hits = []

        for row in rows:
            total += row.computed_cost_usd
            total_input += row.input_tokens
            total_output += row.output_tokens
            by_agent[row.agent_name] = by_agent.get(row.agent_name, 0) + row.computed_cost_usd
            by_model[row.model_used] = by_model.get(row.model_used, 0) + row.computed_cost_usd
            if row.prompt_cache_hit_rate is not None:
                cache_hits.append(row.prompt_cache_hit_rate)

        return {
            "total_cost_usd": round(total, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "by_agent": by_agent,
            "by_model": by_model,
            "avg_cache_hit_rate": (sum(cache_hits) / len(cache_hits)) if cache_hits else None,
        }
