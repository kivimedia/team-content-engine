"""Seed database with default creators, templates, and prompts from the PRD."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tce.models.creator_profile import CreatorProfile
from tce.models.pattern_template import PatternTemplate
from tce.models.prompt_version import PromptVersion

logger = structlog.get_logger()

# PRD Section 7 + 14: Default creator profiles
DEFAULT_CREATORS = [
    {
        "creator_name": "Omri Barak",
        "allowed_influence_weight": 0.24,
        "style_notes": (
            "Big-news hooks, paradox, famous names, urgency, "
            "'why this matters now'. Curiosity + strategic depth."
        ),
        "voice_axes": {
            "curiosity": 9,
            "sharpness": 7,
            "practicality": 5,
            "strategic_depth": 7,
            "emotional_intensity": 7,
            "sentence_punch": 8,
            "executive_clarity": 6,
            "contrarian_heat": 6,
            "friendliness": 6,
            "urgency": 9,
        },
        "top_patterns": [
            "big_shift_explainer",
            "second_order_implication",
            "weekly_roundup",
        ],
    },
    {
        "creator_name": "Ben Z. Yabets",
        "allowed_influence_weight": 0.20,
        "style_notes": (
            "Second-person diagnosis, 3-point frameworks, strong positioning, clean keyword CTAs."
        ),
        "voice_axes": {
            "curiosity": 6,
            "sharpness": 8,
            "practicality": 8,
            "strategic_depth": 6,
            "emotional_intensity": 7,
            "sentence_punch": 9,
            "executive_clarity": 8,
            "contrarian_heat": 7,
            "friendliness": 7,
            "urgency": 6,
        },
        "top_patterns": [
            "contrarian_diagnosis",
            "tactical_workflow_guide",
            "comment_keyword_cta_guide",
        ],
    },
    {
        "creator_name": "Nathan Savis",
        "allowed_influence_weight": 0.20,
        "style_notes": (
            "Contrarian openings, teardown energy, proof, "
            "high-tension copy. Personal failure as credibility."
        ),
        "voice_axes": {
            "curiosity": 6,
            "sharpness": 9,
            "practicality": 7,
            "strategic_depth": 6,
            "emotional_intensity": 9,
            "sentence_punch": 9,
            "executive_clarity": 6,
            "contrarian_heat": 9,
            "friendliness": 5,
            "urgency": 7,
        },
        "top_patterns": [
            "teardown_myth_busting",
            "contrarian_diagnosis",
            "case_study_build_story",
        ],
    },
    {
        "creator_name": "Eden Bibas",
        "allowed_influence_weight": 0.18,
        "style_notes": (
            "Practical AI utility posts, bullet-based clarity, guide/WhatsApp conversion CTAs."
        ),
        "voice_axes": {
            "curiosity": 6,
            "sharpness": 5,
            "practicality": 10,
            "strategic_depth": 4,
            "emotional_intensity": 4,
            "sentence_punch": 7,
            "executive_clarity": 8,
            "contrarian_heat": 3,
            "friendliness": 8,
            "urgency": 5,
        },
        "top_patterns": [
            "tactical_workflow_guide",
            "hidden_feature_shortcut",
            "comment_keyword_cta_guide",
        ],
    },
    {
        "creator_name": "Alex Kap",
        "allowed_influence_weight": 0.18,
        "style_notes": (
            "Strategic depth, second-order implications, 'what changed / what it means' analysis."
        ),
        "voice_axes": {
            "curiosity": 7,
            "sharpness": 7,
            "practicality": 6,
            "strategic_depth": 10,
            "emotional_intensity": 6,
            "sentence_punch": 7,
            "executive_clarity": 9,
            "contrarian_heat": 6,
            "friendliness": 5,
            "urgency": 5,
        },
        "top_patterns": [
            "second_order_implication",
            "big_shift_explainer",
            "founder_reflection",
        ],
    },
]

# PRD Appendix B: 10 template families
DEFAULT_TEMPLATES = [
    {
        "template_name": "Big Shift Explainer",
        "template_family": "big_shift_explainer",
        "best_for": "Monday: Make a fast-moving AI development legible and relevant",
        "hook_formula": ("News hook with paradox/famous name -> Why it matters to YOU"),
        "body_formula": ("2-4 proof blocks -> Second-order implication turn -> Weekly guide CTA"),
        "platform_fit": "both",
        "source_influence_weights": {
            "Omri Barak": 0.35,
            "Alex Kap": 0.30,
            "Nathan Savis": 0.20,
            "Ben Z. Yabets": 0.15,
        },
        "anti_patterns": (
            "Don't bury the shift under anecdotes. Don't use "
            "'breaking' unless it is. Don't list 10 implications."
        ),
    },
    {
        "template_name": "Tactical Workflow Guide",
        "template_family": "tactical_workflow_guide",
        "best_for": "Tuesday: Deliver immediate utility with a repeatable process",
        "hook_formula": "State the outcome first -> Why existing approaches fail",
        "body_formula": (
            "3-5 numbered steps (what + why + mistake to avoid) -> "
            "Compounding benefit turn -> Weekly guide CTA"
        ),
        "platform_fit": "both",
        "source_influence_weights": {
            "Eden Bibas": 0.35,
            "Ben Z. Yabets": 0.30,
            "Alex Kap": 0.20,
            "Omri Barak": 0.15,
        },
        "anti_patterns": (
            "Don't start with 'I've been using AI for X months.' "
            "Don't list 10 tools without connections."
        ),
    },
    {
        "template_name": "Contrarian Diagnosis",
        "template_family": "contrarian_diagnosis",
        "best_for": "Wednesday: Challenge a lazy or outdated assumption",
        "hook_formula": ("State conventional wisdom -> Acknowledge why it feels right"),
        "body_formula": ("2-3 dismantling blocks -> Better framing turn -> Weekly guide CTA"),
        "platform_fit": "both",
        "source_influence_weights": {
            "Nathan Savis": 0.35,
            "Ben Z. Yabets": 0.25,
            "Omri Barak": 0.20,
            "Alex Kap": 0.20,
        },
        "anti_patterns": (
            "Don't be contrarian for its own sake. Don't strawman. "
            "Always provide the better alternative."
        ),
    },
    {
        "template_name": "Case Study / Build Story",
        "template_family": "case_study_build_story",
        "best_for": "Thursday: Show proof through a real workflow or teardown",
        "hook_formula": "Lead with the result -> What problem existed before",
        "body_formula": (
            "3-4 build blocks (what + tool + result) -> "
            "Generalizable lesson turn -> Weekly guide CTA"
        ),
        "platform_fit": "both",
        "source_influence_weights": {
            "Nathan Savis": 0.30,
            "Eden Bibas": 0.25,
            "Alex Kap": 0.25,
            "Ben Z. Yabets": 0.20,
        },
        "anti_patterns": (
            "Don't present hypotheticals as real. Don't skip the struggle. Don't hide the tools."
        ),
    },
    {
        "template_name": "Second-Order Implication",
        "template_family": "second_order_implication",
        "best_for": "Friday: Explain consequences others aren't discussing",
        "hook_formula": (
            "Widely-reported first-order event -> 'But here's what nobody is talking about'"
        ),
        "body_formula": (
            "2-3 second-order analysis blocks -> Strategic recommendation turn -> Weekly guide CTA"
        ),
        "platform_fit": "both",
        "source_influence_weights": {
            "Alex Kap": 0.35,
            "Omri Barak": 0.25,
            "Nathan Savis": 0.20,
            "Ben Z. Yabets": 0.20,
        },
        "anti_patterns": (
            "Don't just summarize news. Don't predict without "
            "reasoning. Don't make it so abstract there's no takeaway."
        ),
    },
    {
        "template_name": "Hidden Feature / Tool Shortcut",
        "template_family": "hidden_feature_shortcut",
        "best_for": "Tuesday alt: One specific trick, deep not broad",
        "hook_formula": "Tool reveal with vivid everyday metaphor",
        "body_formula": (
            "Bullet-based feature list with bridge to action -> "
            "Permission grant turn -> Weekly guide CTA"
        ),
        "platform_fit": "both",
        "source_influence_weights": {
            "Eden Bibas": 0.40,
            "Ben Z. Yabets": 0.30,
            "Omri Barak": 0.15,
            "Alex Kap": 0.15,
        },
    },
    {
        "template_name": "Teardown / Myth Busting",
        "template_family": "teardown_myth_busting",
        "best_for": "Wednesday alt: Dismantle a claim with receipts",
        "hook_formula": ("Direct attack on conventional wisdom + personal failure"),
        "body_formula": ("Problem -> evidence -> reframe -> proof of new approach"),
        "platform_fit": "both",
        "source_influence_weights": {
            "Nathan Savis": 0.40,
            "Omri Barak": 0.25,
            "Ben Z. Yabets": 0.20,
            "Alex Kap": 0.15,
        },
    },
    {
        "template_name": "Weekly Roundup",
        "template_family": "weekly_roundup",
        "best_for": "Friday alt: 3-5 curated items with takes + guide CTA",
        "hook_formula": "This week in AI: the stories that matter",
        "body_formula": ("3-5 curated items with 1-2 sentence take each -> Strong guide CTA"),
        "platform_fit": "both",
        "source_influence_weights": {
            "Omri Barak": 0.35,
            "Alex Kap": 0.35,
            "Ben Z. Yabets": 0.15,
            "Nathan Savis": 0.15,
        },
    },
    {
        "template_name": "Founder Reflection",
        "template_family": "founder_reflection",
        "best_for": "Personal insight tied to a professional lesson",
        "hook_formula": "Personal moment -> professional realization",
        "body_formula": ("Narrative arc (struggle -> insight -> lesson) -> Actionable takeaway"),
        "platform_fit": "both",
        "source_influence_weights": {
            "Nathan Savis": 0.30,
            "Alex Kap": 0.30,
            "Omri Barak": 0.20,
            "Ben Z. Yabets": 0.20,
        },
    },
    {
        "template_name": "Comment Keyword CTA Guide",
        "template_family": "comment_keyword_cta_guide",
        "best_for": "Posts optimized for comment-to-DM conversion",
        "hook_formula": "Value tease -> build desire for deliverable",
        "body_formula": ("Demonstrate value -> reveal there's more -> comment keyword CTA"),
        "platform_fit": "facebook",
        "source_influence_weights": {
            "Ben Z. Yabets": 0.35,
            "Eden Bibas": 0.35,
            "Omri Barak": 0.15,
            "Nathan Savis": 0.15,
        },
    },
]

# PRD Appendix E: Starter prompts (abbreviated — full prompts in agents)
DEFAULT_PROMPTS = [
    {
        "agent_name": "story_strategist",
        "prompt_text": (
            "You are the Story Strategist for Team Content Engine. "
            "Your job is the most consequential decision each day: "
            "choosing what to write about and how to frame it."
        ),
        "model_target": "claude-opus-4-20250514",
    },
    {
        "agent_name": "facebook_writer",
        "prompt_text": (
            "You are the Facebook Writer for Team Content Engine. "
            "Your job is to write a scroll-stopping, comment-triggering "
            "post that makes people engage."
        ),
        "model_target": "claude-sonnet-4-20250514",
    },
    {
        "agent_name": "qa_agent",
        "prompt_text": (
            "You are the QA Agent for Team Content Engine. You are the "
            "last gate before content goes to the operator for approval."
        ),
        "model_target": "claude-sonnet-4-20250514",
    },
]


async def seed_database(db: AsyncSession) -> dict[str, int]:
    """Seed the database with default data. Idempotent."""
    counts = {"creators": 0, "templates": 0, "prompts": 0}

    # Seed creators
    for creator_data in DEFAULT_CREATORS:
        result = await db.execute(
            select(CreatorProfile).where(
                CreatorProfile.creator_name == creator_data["creator_name"]
            )
        )
        if not result.scalar_one_or_none():
            db.add(CreatorProfile(**creator_data))
            counts["creators"] += 1

    # Seed templates
    for tpl_data in DEFAULT_TEMPLATES:
        result = await db.execute(
            select(PatternTemplate).where(
                PatternTemplate.template_name == tpl_data["template_name"]
            )
        )
        if not result.scalar_one_or_none():
            db.add(PatternTemplate(**tpl_data))
            counts["templates"] += 1

    # Seed prompts
    for prompt_data in DEFAULT_PROMPTS:
        result = await db.execute(
            select(PromptVersion).where(
                PromptVersion.agent_name == prompt_data["agent_name"],
                PromptVersion.is_active.is_(True),
            )
        )
        if not result.scalar_one_or_none():
            db.add(
                PromptVersion(
                    agent_name=prompt_data["agent_name"],
                    version=1,
                    prompt_text=prompt_data["prompt_text"],
                    model_target=prompt_data["model_target"],
                    is_active=True,
                    status="active",
                    created_by="seed",
                )
            )
            counts["prompts"] += 1

    await db.flush()
    logger.info("seed.complete", **counts)
    return counts
