"""Agent framework — all content engine agents."""

# Import all concrete agents so @register_agent decorators fire
from tce.agents import (  # noqa: F401
    corpus_analyst,
    creative_director,
    cta_agent,
    docx_guide_builder,
    engagement_scorer,
    founder_voice_extractor,
    learning_loop,
    pattern_miner,
    platform_writer,
    qa_agent,
    research_agent,
    story_strategist,
    trend_scout,
    weekly_planner,
)
from tce.agents.base import AgentBase
from tce.agents.registry import agent_registry, register_agent

__all__ = ["AgentBase", "agent_registry", "register_agent"]
