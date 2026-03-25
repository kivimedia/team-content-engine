"""Tests for agent registry."""

# Import all agents to trigger registration
from tce.agents.corpus_analyst import CorpusAnalyst
from tce.agents.creative_director import CreativeDirector
from tce.agents.cta_agent import CTAAgent
from tce.agents.docx_guide_builder import DocxGuideBuilder
from tce.agents.engagement_scorer import EngagementScorer
from tce.agents.learning_loop import LearningLoop
from tce.agents.pattern_miner import PatternMiner
from tce.agents.platform_writer import FacebookWriter, LinkedInWriter
from tce.agents.qa_agent import QAAgent
from tce.agents.research_agent import ResearchAgent
from tce.agents.story_strategist import StoryStrategist
from tce.agents.trend_scout import TrendScout
from tce.agents.registry import get_agent_class, agent_registry


def test_all_agents_registered():
    """All 12 agents should be in the registry."""
    registry = agent_registry()
    expected = [
        "corpus_analyst",
        "engagement_scorer",
        "pattern_miner",
        "trend_scout",
        "research_agent",
        "story_strategist",
        "facebook_writer",
        "linkedin_writer",
        "cta_agent",
        "creative_director",
        "docx_guide_builder",
        "qa_agent",
        "learning_loop",
    ]
    for name in expected:
        assert name in registry, f"Agent '{name}' not registered"


def test_get_agent_class():
    """Can retrieve agent classes by name."""
    cls = get_agent_class("corpus_analyst")
    assert cls is CorpusAnalyst


def test_agent_default_models():
    """Check model assignments per PRD Section 37."""
    assert CorpusAnalyst.default_model == "claude-sonnet-4-20250514"
    assert EngagementScorer.default_model == "claude-haiku-4-5-20251001"
    assert StoryStrategist.default_model == "claude-opus-4-20250514"
    assert FacebookWriter.default_model == "claude-sonnet-4-20250514"
    assert LinkedInWriter.default_model == "claude-sonnet-4-20250514"
    assert QAAgent.default_model == "claude-sonnet-4-20250514"
