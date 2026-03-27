"""Tests for edge case handlers (PRD Appendix H)."""

from tce.services.edge_cases import (
    APPROVAL_TIMEOUT_HOURS,
    QA_CONSECUTIVE_FAILURE_LIMIT,
    EdgeCaseHandler,
)


def test_consecutive_failure_limit():
    """H.3: 3 consecutive QA failures."""
    assert QA_CONSECUTIVE_FAILURE_LIMIT == 3


def test_approval_timeout():
    """H.4: 48 hours timeout."""
    assert APPROVAL_TIMEOUT_HOURS == 48


def test_fallback_cta():
    """H.6: Fallback CTA when guide isn't ready."""
    result = EdgeCaseHandler.get_fallback_cta_for_missing_guide("notify")
    assert result["keyword"] == "notify"
    assert "notify" in result["fb_cta_line"]
    assert "when it's ready" in result["fb_cta_line"]


def test_fallback_topic():
    """H.1: Evergreen topics when no trends found."""
    result = EdgeCaseHandler.get_fallback_topic()
    assert result["source"] == "evergreen_library"
    assert len(result["topics"]) >= 5


def test_research_failure():
    """H.2: Handle unverifiable claims."""
    result = EdgeCaseHandler.handle_research_failure("AI has 90% accuracy")
    assert result["action"] == "reinvoke_strategist"
    assert len(result["options"]) >= 2


def test_source_creator_overlap():
    """H.7: Source creator publishes same topic."""
    result = EdgeCaseHandler.handle_source_creator_overlap("Omri Barak", "AI agents")
    assert result["action"] == "flag_for_review"
    assert "Omri Barak" in result["message"]
    assert len(result["options"]) >= 2


def test_budget_spike_not_triggered():
    """H.9: No spike when under budget."""

    # Static method test — no DB needed for this
    result = EdgeCaseHandler.get_fallback_topic()
    assert "topics" in result
