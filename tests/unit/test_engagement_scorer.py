"""Tests for the engagement scoring logic."""

from tce.agents.engagement_scorer import (
    CONFIDENCE_MULTIPLIERS,
    DEFAULT_COMMENTS_WEIGHT,
    DEFAULT_SHARES_WEIGHT,
)


def test_confidence_multipliers():
    assert CONFIDENCE_MULTIPLIERS["A"] == 1.00
    assert CONFIDENCE_MULTIPLIERS["B"] == 0.75
    assert CONFIDENCE_MULTIPLIERS["C"] == 0.40


def test_scoring_formula():
    """Test the default scoring formula from PRD Section 12.2."""
    shares = 32
    comments = 89
    raw_score = (shares * DEFAULT_SHARES_WEIGHT) + (comments * DEFAULT_COMMENTS_WEIGHT)
    assert raw_score == (32 * 3.0) + (89 * 1.0)
    assert raw_score == 185.0

    # Confidence A
    final_a = raw_score * CONFIDENCE_MULTIPLIERS["A"]
    assert final_a == 185.0

    # Confidence B
    final_b = raw_score * CONFIDENCE_MULTIPLIERS["B"]
    assert final_b == 138.75

    # Confidence C
    final_c = raw_score * CONFIDENCE_MULTIPLIERS["C"]
    assert final_c == 74.0


def test_zero_engagement():
    """Posts with no visible engagement get zero score."""
    shares = 0
    comments = 0
    raw_score = (shares * DEFAULT_SHARES_WEIGHT) + (comments * DEFAULT_COMMENTS_WEIGHT)
    assert raw_score == 0.0
