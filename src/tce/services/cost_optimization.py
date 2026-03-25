"""Cost optimization service (PRD Section 36.8-36.9).

Analyzes spending patterns and recommends optimizations.
"""

from __future__ import annotations

from typing import Any

import structlog

from tce.settings import settings

logger = structlog.get_logger()

# PRD Section 36.8: Prompt caching implementation guide
CACHE_SEGMENTS = [
    {
        "segment": "System prompt per agent",
        "approx_tokens": "2,000-5,000",
        "changes": "On prompt version change",
        "expected_hit_rate": 0.99,
    },
    {
        "segment": "House voice config",
        "approx_tokens": "1,500-3,000",
        "changes": "Weekly at most",
        "expected_hit_rate": 0.95,
    },
    {
        "segment": "Template library",
        "approx_tokens": "3,000-6,000",
        "changes": "Weekly at most",
        "expected_hit_rate": 0.95,
    },
    {
        "segment": "Scoring rubric + QA thresholds",
        "approx_tokens": "1,000-2,000",
        "changes": "Rarely",
        "expected_hit_rate": 0.99,
    },
    {
        "segment": "Creator profiles",
        "approx_tokens": "1,500-3,000",
        "changes": "On new corpus ingestion",
        "expected_hit_rate": 0.98,
    },
    {
        "segment": "CTA rules",
        "approx_tokens": "500-1,000",
        "changes": "Rarely",
        "expected_hit_rate": 0.99,
    },
]

# PRD Section 36.9: Optimization options
OPTIMIZATION_OPTIONS = [
    {
        "option": "Downgrade QA from Opus to Sonnet",
        "savings_per_month": 50,
        "risk": "May miss subtle quality issues",
        "recommended": False,
    },
    {
        "option": "Batch API for Research Agent",
        "savings_per_month": 45,
        "risk": "Requires 24h planning ahead",
        "recommended": True,
    },
    {
        "option": "Reduce to 3 posts/week",
        "savings_per_month": 210,
        "risk": "40% less content volume",
        "recommended": False,
    },
]


class CostOptimizationService:
    """Analyzes costs and recommends optimizations."""

    def __init__(
        self,
        daily_spend: float = 0,
        monthly_spend: float = 0,
        cache_hit_rate: float = 0,
    ) -> None:
        self.daily_spend = daily_spend
        self.monthly_spend = monthly_spend
        self.cache_hit_rate = cache_hit_rate

    def analyze(self) -> dict[str, Any]:
        """Produce a cost optimization analysis."""
        daily_budget = float(settings.daily_budget_usd)
        monthly_budget = float(settings.monthly_budget_usd)

        recommendations = []

        # Cache optimization
        if self.cache_hit_rate < 0.80:
            recommendations.append({
                "priority": "high",
                "recommendation": (
                    "Prompt cache hit rate is below 80%. "
                    "Investigate — prompts may be changing too "
                    "frequently or agent calls too spread out."
                ),
                "expected_savings": "30-40% on input token costs",
            })

        # Budget utilization
        if self.monthly_spend > monthly_budget * 0.9:
            recommendations.append({
                "priority": "high",
                "recommendation": (
                    f"Monthly spend at {self.monthly_spend / monthly_budget * 100:.0f}% "
                    "of budget. Consider model downgrades or reduced cadence."
                ),
                "expected_savings": "varies",
            })

        # Add standard optimization options
        for opt in OPTIMIZATION_OPTIONS:
            if opt["recommended"]:
                recommendations.append({
                    "priority": "medium",
                    "recommendation": opt["option"],
                    "expected_savings": f"~${opt['savings_per_month']}/month",
                    "risk": opt["risk"],
                })

        return {
            "current_daily_spend": self.daily_spend,
            "current_monthly_spend": self.monthly_spend,
            "daily_budget": daily_budget,
            "monthly_budget": monthly_budget,
            "cache_hit_rate": self.cache_hit_rate,
            "cache_segments": CACHE_SEGMENTS,
            "recommendations": recommendations,
            "optimization_options": OPTIMIZATION_OPTIONS,
            "estimated_floor": "$350-400/month with all aggressive measures",
        }

    def generate_weekly_cost_report(
        self,
        weekly_costs: dict[str, float],
        prev_week_costs: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Generate the weekly cost report (PRD Section 36.6)."""
        total = sum(weekly_costs.values())
        by_agent = dict(
            sorted(weekly_costs.items(), key=lambda x: -x[1])
        )

        report: dict[str, Any] = {
            "total_spend": round(total, 2),
            "cost_per_post": round(total / 5, 2) if total > 0 else 0,
            "by_agent": by_agent,
            "cache_hit_rate": self.cache_hit_rate,
        }

        if prev_week_costs:
            prev_total = sum(prev_week_costs.values())
            delta = total - prev_total
            delta_pct = (
                (delta / prev_total * 100) if prev_total > 0 else 0
            )
            report["week_over_week_change"] = round(delta, 2)
            report["week_over_week_pct"] = round(delta_pct, 1)

        return report
