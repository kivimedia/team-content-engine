"""Tests for competitor monitoring (PRD Section 43.4)."""

from tce.services.competitor_monitor import (
    SOURCE_CREATORS,
    CompetitorMonitorService,
)


def test_five_source_creators():
    """PRD: 5 source creators to monitor."""
    assert len(SOURCE_CREATORS) == 5


def test_creator_names():
    names = {c["name"] for c in SOURCE_CREATORS}
    assert "Omri Barak" in names
    assert "Alex Kap" in names


def test_topic_overlap_none():
    service = CompetitorMonitorService()
    result = service.check_topic_overlap(
        "quantum computing breakthroughs",
        [{"creator_name": "Omri", "topic": "AI model training"}],
    )
    assert result["overlaps_found"] == 0
    assert not result["should_review"]


def test_topic_overlap_detected():
    service = CompetitorMonitorService()
    result = service.check_topic_overlap(
        "OpenAI launches new agent system",
        [
            {
                "creator_name": "Omri",
                "topic": "OpenAI new agent feature released",
            }
        ],
    )
    assert result["overlaps_found"] > 0
    assert result["should_review"]


def test_trend_convergence():
    service = CompetitorMonitorService()
    posts = [
        {"creator_name": "Omri", "topic": "AI agents are changing work"},
        {"creator_name": "Alex", "topic": "agents will replace managers"},
        {"creator_name": "Nathan", "topic": "marketing automation tools"},
    ]
    convergences = service.detect_trend_convergence(posts)
    assert len(convergences) > 0
    # "agents" should appear from both Omri and Alex
    agent_conv = [
        c for c in convergences if c["keyword"] == "agents"
    ]
    assert len(agent_conv) > 0


def test_get_source_creators():
    service = CompetitorMonitorService()
    creators = service.get_source_creators()
    assert len(creators) == 5
