"""Tests for cost computation logic."""

from tce.services.cost_tracker import compute_cost


def test_compute_cost_sonnet():
    """Sonnet pricing: $3/M input, $15/M output."""
    cost = compute_cost(
        model="claude-sonnet-4-20250514",
        input_tokens=10000,
        output_tokens=2000,
    )
    expected = (10000 / 1_000_000) * 3.0 + (2000 / 1_000_000) * 15.0
    assert abs(cost - expected) < 0.0001


def test_compute_cost_opus():
    """Opus pricing: $15/M input, $75/M output."""
    cost = compute_cost(
        model="claude-opus-4-20250514",
        input_tokens=10000,
        output_tokens=2000,
    )
    expected = (10000 / 1_000_000) * 15.0 + (2000 / 1_000_000) * 75.0
    assert abs(cost - expected) < 0.0001


def test_compute_cost_with_cache():
    """Cache read tokens are cheaper."""
    cost = compute_cost(
        model="claude-sonnet-4-20250514",
        input_tokens=5000,
        output_tokens=1000,
        cache_read_tokens=10000,
    )
    expected = (
        (5000 / 1_000_000) * 3.0
        + (1000 / 1_000_000) * 15.0
        + (10000 / 1_000_000) * 0.3
    )
    assert abs(cost - expected) < 0.0001


def test_compute_cost_haiku():
    """Haiku is the cheapest tier."""
    cost = compute_cost(
        model="claude-haiku-4-5-20251001",
        input_tokens=10000,
        output_tokens=2000,
    )
    expected = (10000 / 1_000_000) * 0.80 + (2000 / 1_000_000) * 4.0
    assert abs(cost - expected) < 0.0001
