"""Tests for trend_scout post-LLM filtering and composite-score computation.

These exercise the pure-Python ranking logic without making LLM calls. The DAG
test surface for trend_scout itself lives in tests/integration; here we cover
the new hook_strength filter and multiplicative composite_score derivation
that ship alongside the Reddit demand layer.
"""

from __future__ import annotations

import pytest


def _filter_trends(raw_trends: list[dict], min_hook_strength: float = 4.0,
                   has_search_results: bool = True) -> tuple[list[dict], dict[str, int]]:
    """Mirrors the hard-filter + composite-score block in trend_scout._execute.

    Kept in sync manually because trend_scout's _execute is async and depends on
    the agent base class; testing the pure logic here gives fast unit coverage.
    If trend_scout's filter logic changes, update this helper too.
    """
    trends: list[dict] = []
    rejected_stale = 0
    rejected_unsourced = 0
    rejected_hookless = 0
    for t in raw_trends:
        freshness = t.get("freshness")
        if freshness is not None:
            try:
                if float(freshness) > 336:
                    rejected_stale += 1
                    continue
            except (ValueError, TypeError):
                pass
        if has_search_results and not t.get("source_url"):
            rejected_unsourced += 1
            continue
        hook_strength = t.get("hook_strength")
        if hook_strength is not None:
            try:
                if float(hook_strength) < min_hook_strength:
                    rejected_hookless += 1
                    continue
            except (ValueError, TypeError):
                pass
        try:
            f = max(0.1, 1.0 - float(freshness or 0) / 336.0)
            r = float(t.get("relevance_score", 5)) / 10.0
            d = float(t.get("demand_velocity", 5)) / 10.0
            h = float(t.get("hook_strength", 5)) / 10.0
            ev_map = {"easy": 1.0, "moderate": 0.7, "hard": 0.4}
            e = ev_map.get(str(t.get("evidence_available", "moderate")).lower(), 0.7)
            t["composite_score"] = round(f * r * d * h * e, 4)
        except (ValueError, TypeError):
            t["composite_score"] = 0.0
        trends.append(t)
    trends.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    return trends, {
        "stale": rejected_stale,
        "unsourced": rejected_unsourced,
        "hookless": rejected_hookless,
    }


def test_drops_stale_trends_over_14_days():
    raw = [
        {"trend_id": "fresh", "freshness": 12, "source_url": "x", "hook_strength": 8,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
        {"trend_id": "stale", "freshness": 400, "source_url": "x", "hook_strength": 8,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
    ]
    trends, rejected = _filter_trends(raw)
    assert [t["trend_id"] for t in trends] == ["fresh"]
    assert rejected["stale"] == 1


def test_drops_hookless_trends_below_threshold():
    raw = [
        {"trend_id": "strong-hook", "freshness": 12, "source_url": "x", "hook_strength": 8,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
        {"trend_id": "weak-hook", "freshness": 12, "source_url": "x", "hook_strength": 2,
         "relevance_score": 9, "demand_velocity": 9, "evidence_available": "easy"},
    ]
    trends, rejected = _filter_trends(raw, min_hook_strength=4)
    assert [t["trend_id"] for t in trends] == ["strong-hook"]
    assert rejected["hookless"] == 1


def test_min_hook_strength_is_configurable():
    """Workspace can lower the floor when topic supply is starved."""
    raw = [
        {"trend_id": "ok", "freshness": 12, "source_url": "x", "hook_strength": 3,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
    ]
    trends_strict, _ = _filter_trends(raw, min_hook_strength=4)
    trends_loose, _ = _filter_trends(raw, min_hook_strength=2)
    assert trends_strict == []
    assert len(trends_loose) == 1


def test_composite_score_is_multiplicative():
    """Demonstrates the formula: weakness in any single axis dominates."""
    raw = [
        # All factors strong
        {"trend_id": "strong-all", "freshness": 12, "source_url": "x", "hook_strength": 9,
         "relevance_score": 9, "demand_velocity": 9, "evidence_available": "easy"},
        # One weak axis (demand)
        {"trend_id": "weak-demand", "freshness": 12, "source_url": "x", "hook_strength": 9,
         "relevance_score": 9, "demand_velocity": 4, "evidence_available": "easy"},
    ]
    trends, _ = _filter_trends(raw)
    by_id = {t["trend_id"]: t for t in trends}
    # Strong-all should win by a wide margin under multiplicative scoring
    assert by_id["strong-all"]["composite_score"] > by_id["weak-demand"]["composite_score"]
    # Specifically, weak-demand has demand_factor=0.4 (vs 0.9), so should be ~0.4/0.9 of strong
    ratio = by_id["weak-demand"]["composite_score"] / by_id["strong-all"]["composite_score"]
    assert 0.40 <= ratio <= 0.50


def test_results_sorted_by_composite_score_desc():
    raw = [
        {"trend_id": "low", "freshness": 12, "source_url": "x", "hook_strength": 5,
         "relevance_score": 5, "demand_velocity": 5, "evidence_available": "moderate"},
        {"trend_id": "high", "freshness": 12, "source_url": "x", "hook_strength": 9,
         "relevance_score": 9, "demand_velocity": 9, "evidence_available": "easy"},
        {"trend_id": "mid", "freshness": 50, "source_url": "x", "hook_strength": 7,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "moderate"},
    ]
    trends, _ = _filter_trends(raw)
    assert [t["trend_id"] for t in trends] == ["high", "mid", "low"]


def test_unsourced_trends_dropped_when_search_results_present():
    raw = [
        {"trend_id": "sourced", "freshness": 12, "source_url": "x", "hook_strength": 7,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
        {"trend_id": "no-url", "freshness": 12, "hook_strength": 7,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
    ]
    trends, rejected = _filter_trends(raw, has_search_results=True)
    assert [t["trend_id"] for t in trends] == ["sourced"]
    assert rejected["unsourced"] == 1


def test_unsourced_allowed_when_no_search_results():
    """Knowledge-fallback path: LLM may report 'unknown' source_url."""
    raw = [
        {"trend_id": "from-knowledge", "freshness": 12, "hook_strength": 7,
         "relevance_score": 7, "demand_velocity": 7, "evidence_available": "easy"},
    ]
    trends, rejected = _filter_trends(raw, has_search_results=False)
    assert len(trends) == 1
    assert rejected["unsourced"] == 0


def test_missing_factors_use_safe_defaults():
    raw = [
        {"trend_id": "minimal", "freshness": 24, "source_url": "x", "hook_strength": 5},
    ]
    trends, _ = _filter_trends(raw)
    assert len(trends) == 1
    # Should not crash; composite_score should be reasonable using defaults
    assert 0.05 <= trends[0]["composite_score"] <= 1.0


@pytest.mark.parametrize("evidence,expected_factor", [
    ("easy", 1.0), ("moderate", 0.7), ("hard", 0.4), ("EASY", 1.0), ("unknown", 0.7),
])
def test_evidence_factor_mapping(evidence, expected_factor):
    raw = [
        {"trend_id": "x", "freshness": 0, "source_url": "u", "hook_strength": 10,
         "relevance_score": 10, "demand_velocity": 10, "evidence_available": evidence},
    ]
    trends, _ = _filter_trends(raw)
    # All other factors = 1.0, so composite_score == evidence_factor
    assert abs(trends[0]["composite_score"] - expected_factor) < 0.01
