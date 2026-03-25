"""Pre-built workflow definitions for common pipeline configurations."""

from tce.orchestrator.step import PipelineStep

# Full daily content workflow (PRD Section 15.3)
DAILY_CONTENT_WORKFLOW = [
    PipelineStep(agent_name="trend_scout", depends_on=[], timeout_seconds=60),
    PipelineStep(agent_name="story_strategist", depends_on=["trend_scout"], timeout_seconds=120),
    PipelineStep(
        agent_name="research_agent", depends_on=["story_strategist"], timeout_seconds=120
    ),
    PipelineStep(
        agent_name="facebook_writer",
        depends_on=["story_strategist", "research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="linkedin_writer",
        depends_on=["story_strategist", "research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="cta_agent", depends_on=["story_strategist"], timeout_seconds=60
    ),
    PipelineStep(
        agent_name="creative_director",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="qa_agent",
        depends_on=["facebook_writer", "linkedin_writer", "cta_agent", "creative_director"],
        timeout_seconds=120,
    ),
]

# Corpus ingestion workflow (PRD Section 15.1)
CORPUS_INGESTION_WORKFLOW = [
    PipelineStep(agent_name="corpus_analyst", depends_on=[], timeout_seconds=300),
    PipelineStep(agent_name="engagement_scorer", depends_on=["corpus_analyst"], timeout_seconds=60),
    PipelineStep(
        agent_name="pattern_miner", depends_on=["engagement_scorer"], timeout_seconds=180
    ),
]

# Weekly planning workflow (PRD Section 15.2)
WEEKLY_PLANNING_WORKFLOW = [
    PipelineStep(agent_name="trend_scout", depends_on=[], timeout_seconds=120),
    PipelineStep(agent_name="story_strategist", depends_on=["trend_scout"], timeout_seconds=180),
    PipelineStep(
        agent_name="research_agent", depends_on=["story_strategist"], timeout_seconds=180
    ),
    PipelineStep(agent_name="cta_agent", depends_on=["story_strategist"], timeout_seconds=60),
    PipelineStep(
        agent_name="docx_guide_builder",
        depends_on=["story_strategist", "research_agent", "cta_agent"],
        timeout_seconds=300,
    ),
]

# Weekly learning workflow (PRD Section 15.4)
WEEKLY_LEARNING_WORKFLOW = [
    PipelineStep(agent_name="learning_loop", depends_on=[], timeout_seconds=180),
]

# Analysis-only workflow (for corpus exploration)
ANALYSIS_WORKFLOW = [
    PipelineStep(agent_name="corpus_analyst", depends_on=[], timeout_seconds=300),
    PipelineStep(agent_name="engagement_scorer", depends_on=["corpus_analyst"], timeout_seconds=60),
    PipelineStep(
        agent_name="pattern_miner", depends_on=["engagement_scorer"], timeout_seconds=180
    ),
]

# Workflow registry
WORKFLOWS: dict[str, list[PipelineStep]] = {
    "daily_content": DAILY_CONTENT_WORKFLOW,
    "corpus_ingestion": CORPUS_INGESTION_WORKFLOW,
    "weekly_planning": WEEKLY_PLANNING_WORKFLOW,
    "weekly_learning": WEEKLY_LEARNING_WORKFLOW,
    "analysis": ANALYSIS_WORKFLOW,
}
