"""Pre-built workflow definitions for common pipeline configurations."""

from tce.orchestrator.step import PipelineStep

# Full daily content workflow (PRD Section 15.3)
DAILY_CONTENT_WORKFLOW = [
    # trend_scout runs 19 web searches then a Claude call with max_tokens=8192;
    # 60s was too tight once the search fan-out grew. Match the weekly_planner workflow.
    PipelineStep(agent_name="trend_scout", depends_on=[], timeout_seconds=180),
    PipelineStep(agent_name="story_strategist", depends_on=["trend_scout"], timeout_seconds=120),
    PipelineStep(agent_name="research_agent", depends_on=["story_strategist"], timeout_seconds=120),
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
    PipelineStep(agent_name="cta_agent", depends_on=["story_strategist"], timeout_seconds=60),
    PipelineStep(
        agent_name="creative_director",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="proof_checker",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="qa_agent",
        depends_on=["facebook_writer", "linkedin_writer", "cta_agent", "creative_director", "proof_checker"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="script_agent",
        depends_on=["qa_agent"],
        timeout_seconds=120,
        optional=True,
    ),
    PipelineStep(
        agent_name="video_agent",
        depends_on=["script_agent", "creative_director"],
        timeout_seconds=600,
        optional=True,
    ),
]

# Corpus ingestion workflow (PRD Section 15.1)
CORPUS_INGESTION_WORKFLOW = [
    PipelineStep(agent_name="corpus_analyst", depends_on=[], timeout_seconds=7200),
    PipelineStep(agent_name="engagement_scorer", depends_on=["corpus_analyst"], timeout_seconds=60),
    PipelineStep(agent_name="pattern_miner", depends_on=["engagement_scorer"], timeout_seconds=180),
]

# Weekly planning workflow (PRD Section 15.2)
WEEKLY_PLANNING_WORKFLOW = [
    PipelineStep(agent_name="trend_scout", depends_on=[], timeout_seconds=120),
    PipelineStep(agent_name="story_strategist", depends_on=["trend_scout"], timeout_seconds=180),
    PipelineStep(agent_name="research_agent", depends_on=["story_strategist"], timeout_seconds=180),
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
    PipelineStep(agent_name="corpus_analyst", depends_on=[], timeout_seconds=1800),
    PipelineStep(
        agent_name="engagement_scorer",
        depends_on=["corpus_analyst"],
        timeout_seconds=60,
    ),
    PipelineStep(
        agent_name="pattern_miner",
        depends_on=["engagement_scorer"],
        timeout_seconds=180,
    ),
]

# Founder voice extraction workflow (PRD Section 50.6)
FOUNDER_VOICE_EXTRACTION_WORKFLOW = [
    PipelineStep(
        agent_name="founder_voice_extractor",
        depends_on=[],
        timeout_seconds=300,
    ),
]

# Weekly planner workflow - runs trend_scout internally and plans all 5 days
WEEKLY_PLANNER_WORKFLOW = [
    PipelineStep(agent_name="weekly_planner", depends_on=[], timeout_seconds=300),
]

# Daily content from pre-planned brief (skips trend_scout + story_strategist)
# Used after weekly_planner has already assigned story_brief for this day
DAILY_FROM_PLAN_WORKFLOW = [
    PipelineStep(agent_name="research_agent", depends_on=[], timeout_seconds=120),
    PipelineStep(
        agent_name="facebook_writer",
        depends_on=["research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="linkedin_writer",
        depends_on=["research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(agent_name="cta_agent", depends_on=[], timeout_seconds=60),
    PipelineStep(
        agent_name="creative_director",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="proof_checker",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="qa_agent",
        depends_on=["facebook_writer", "linkedin_writer", "cta_agent", "creative_director", "proof_checker"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="script_agent",
        depends_on=["qa_agent"],
        timeout_seconds=120,
        optional=True,
    ),
    PipelineStep(
        agent_name="video_agent",
        depends_on=["script_agent", "creative_director"],
        timeout_seconds=600,
        optional=True,
    ),
]

# Guide-only workflow (after all 5 days are generated)
GUIDE_ONLY_WORKFLOW = [
    PipelineStep(agent_name="docx_guide_builder", depends_on=[], timeout_seconds=300),
]

# Polish from user-provided copy (Start From Copy flow)
POLISH_FROM_COPY_WORKFLOW = [
    PipelineStep(agent_name="copy_analyzer", depends_on=[], timeout_seconds=120),
    PipelineStep(agent_name="cta_agent", depends_on=["copy_analyzer"], timeout_seconds=60),
    PipelineStep(
        agent_name="copy_polisher",
        depends_on=["copy_analyzer", "cta_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="creative_director",
        depends_on=["copy_polisher"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="proof_checker",
        depends_on=["copy_polisher"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="qa_agent",
        depends_on=["copy_polisher", "cta_agent", "creative_director", "proof_checker"],
        timeout_seconds=120,
    ),
]

# Video generation workflow (standalone, reads from existing PostPackage context)
VIDEO_GENERATION_WORKFLOW = [
    PipelineStep(
        agent_name="video_agent",
        depends_on=[],
        timeout_seconds=300,
        optional=True,
    ),
]

# Product demo workflow - script + render for product showcase videos
PRODUCT_DEMO_WORKFLOW = [
    PipelineStep(
        agent_name="script_agent",
        depends_on=[],
        timeout_seconds=120,
        optional=True,
    ),
    PipelineStep(
        agent_name="video_agent",
        depends_on=["script_agent"],
        timeout_seconds=600,
    ),
]

# Start From Repo - full package from a GitHub repo with angle (features/whole/fixes)
# Parallels POLISH_FROM_COPY_WORKFLOW so the resulting PostPackage has ALL package features
# (FB + LI + CTA + images + QA + optional video).
START_FROM_REPO_WORKFLOW = [
    PipelineStep(agent_name="repo_scout", depends_on=[], timeout_seconds=300),
    PipelineStep(
        agent_name="repo_storyteller",
        depends_on=["repo_scout"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="research_agent",
        depends_on=["repo_storyteller"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="facebook_writer",
        depends_on=["repo_storyteller", "research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="linkedin_writer",
        depends_on=["repo_storyteller", "research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="cta_agent",
        depends_on=["repo_storyteller"],
        timeout_seconds=60,
    ),
    PipelineStep(
        agent_name="creative_director",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="proof_checker",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="qa_agent",
        depends_on=[
            "facebook_writer",
            "linkedin_writer",
            "cta_agent",
            "creative_director",
            "proof_checker",
        ],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="script_agent",
        depends_on=["qa_agent"],
        timeout_seconds=120,
        optional=True,
    ),
    PipelineStep(
        agent_name="video_agent",
        depends_on=["script_agent", "creative_director"],
        timeout_seconds=600,
        optional=True,
    ),
]

# Weekly repo spotlight - scheduled job variant of start_from_repo + guide section.
# The caller (scheduler) picks the repo and sets `tracked_repo_id` in context.
WEEKLY_REPO_SPOTLIGHT_WORKFLOW = [
    PipelineStep(agent_name="repo_scout", depends_on=[], timeout_seconds=300),
    PipelineStep(
        agent_name="repo_storyteller",
        depends_on=["repo_scout"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="research_agent",
        depends_on=["repo_storyteller"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="facebook_writer",
        depends_on=["repo_storyteller", "research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="linkedin_writer",
        depends_on=["repo_storyteller", "research_agent"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="cta_agent",
        depends_on=["repo_storyteller"],
        timeout_seconds=60,
    ),
    PipelineStep(
        agent_name="creative_director",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="proof_checker",
        depends_on=["facebook_writer", "linkedin_writer"],
        timeout_seconds=180,
    ),
    PipelineStep(
        agent_name="qa_agent",
        depends_on=[
            "facebook_writer",
            "linkedin_writer",
            "cta_agent",
            "creative_director",
            "proof_checker",
        ],
        timeout_seconds=120,
    ),
    PipelineStep(
        agent_name="docx_guide_builder",
        depends_on=["repo_storyteller", "research_agent", "cta_agent"],
        timeout_seconds=300,
    ),
]

# Video lead workflow - produces long-form talking-head scripts (TJ Robertson style)
# Uses coaching-niche trend scout, then story strategist, research, and video lead writer
VIDEO_LEAD_WORKFLOW = [
    PipelineStep(agent_name="trend_scout", depends_on=[], timeout_seconds=120),
    PipelineStep(agent_name="story_strategist", depends_on=["trend_scout"], timeout_seconds=120),
    PipelineStep(agent_name="research_agent", depends_on=["story_strategist"], timeout_seconds=120),
    PipelineStep(
        agent_name="video_lead_writer",
        depends_on=["story_strategist", "research_agent"],
        timeout_seconds=120,
    ),
]

# Workflow registry
WORKFLOWS: dict[str, list[PipelineStep]] = {
    "daily_content": DAILY_CONTENT_WORKFLOW,
    "corpus_ingestion": CORPUS_INGESTION_WORKFLOW,
    "weekly_planning": WEEKLY_PLANNING_WORKFLOW,
    "weekly_learning": WEEKLY_LEARNING_WORKFLOW,
    "analysis": ANALYSIS_WORKFLOW,
    "founder_voice_extraction": FOUNDER_VOICE_EXTRACTION_WORKFLOW,
    "weekly_planner": WEEKLY_PLANNER_WORKFLOW,
    "daily_from_plan": DAILY_FROM_PLAN_WORKFLOW,
    "guide_only": GUIDE_ONLY_WORKFLOW,
    "polish_from_copy": POLISH_FROM_COPY_WORKFLOW,
    "video_generation": VIDEO_GENERATION_WORKFLOW,
    "product_demo": PRODUCT_DEMO_WORKFLOW,
    "video_lead": VIDEO_LEAD_WORKFLOW,
    "start_from_repo": START_FROM_REPO_WORKFLOW,
    "weekly_repo_spotlight": WEEKLY_REPO_SPOTLIGHT_WORKFLOW,
}
