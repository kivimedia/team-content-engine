"""Tests for workflow definitions."""

from tce.orchestrator.workflows import WORKFLOWS


def test_all_workflows_exist():
    """All expected workflows should be defined."""
    expected = ["daily_content", "corpus_ingestion", "weekly_planning", "weekly_learning", "analysis"]
    for name in expected:
        assert name in WORKFLOWS, f"Workflow '{name}' not defined"


def test_daily_content_workflow_steps():
    """Daily content workflow should have the right agents in order."""
    steps = WORKFLOWS["daily_content"]
    agent_names = [s.agent_name for s in steps]
    assert "trend_scout" in agent_names
    assert "story_strategist" in agent_names
    assert "research_agent" in agent_names
    assert "facebook_writer" in agent_names
    assert "linkedin_writer" in agent_names
    assert "cta_agent" in agent_names
    assert "creative_director" in agent_names
    assert "qa_agent" in agent_names


def test_daily_content_dependencies():
    """QA agent should depend on all content agents."""
    steps = WORKFLOWS["daily_content"]
    qa_step = next(s for s in steps if s.agent_name == "qa_agent")
    assert "facebook_writer" in qa_step.depends_on
    assert "linkedin_writer" in qa_step.depends_on
    assert "cta_agent" in qa_step.depends_on
    assert "creative_director" in qa_step.depends_on


def test_corpus_ingestion_workflow():
    """Corpus ingestion should be: analyst -> scorer -> miner."""
    steps = WORKFLOWS["corpus_ingestion"]
    names = [s.agent_name for s in steps]
    assert names == ["corpus_analyst", "engagement_scorer", "pattern_miner"]
