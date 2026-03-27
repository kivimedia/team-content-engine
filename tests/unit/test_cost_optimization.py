"""Tests for cost optimization service (PRD Section 36.8-36.9)."""

from tce.services.cost_optimization import (
    CACHE_SEGMENTS,
    OPTIMIZATION_OPTIONS,
    CostOptimizationService,
)


def test_cache_segments():
    """PRD Section 36.8: 6 cache segments defined."""
    assert len(CACHE_SEGMENTS) == 6
    assert all("segment" in s for s in CACHE_SEGMENTS)
    assert all("expected_hit_rate" in s for s in CACHE_SEGMENTS)


def test_optimization_options():
    """PRD Section 36.9: optimization options defined."""
    assert len(OPTIMIZATION_OPTIONS) >= 3
    assert any("Batch" in o["option"] for o in OPTIMIZATION_OPTIONS)


def test_analyze_basic():
    service = CostOptimizationService(daily_spend=20, monthly_spend=400, cache_hit_rate=0.85)
    result = service.analyze()
    assert "recommendations" in result
    assert "cache_segments" in result
    assert result["current_daily_spend"] == 20


def test_analyze_low_cache():
    """Low cache hit rate should trigger recommendation."""
    service = CostOptimizationService(daily_spend=20, monthly_spend=400, cache_hit_rate=0.50)
    result = service.analyze()
    recs = result["recommendations"]
    assert any("cache" in r["recommendation"].lower() for r in recs)


def test_weekly_cost_report():
    service = CostOptimizationService(cache_hit_rate=0.90)
    report = service.generate_weekly_cost_report(
        weekly_costs={
            "story_strategist": 5.0,
            "facebook_writer": 3.0,
            "linkedin_writer": 3.0,
            "qa_agent": 2.0,
        }
    )
    assert report["total_spend"] == 13.0
    assert report["cost_per_post"] == 2.6


def test_weekly_cost_report_with_comparison():
    service = CostOptimizationService(cache_hit_rate=0.90)
    report = service.generate_weekly_cost_report(
        weekly_costs={"total": 100},
        prev_week_costs={"total": 80},
    )
    assert report["week_over_week_change"] == 20.0
    assert report["week_over_week_pct"] == 25.0
