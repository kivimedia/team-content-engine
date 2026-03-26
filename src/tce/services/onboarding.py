"""Operator onboarding materials (PRD Section 43.6).

Provides quickstart guide, concept glossary, troubleshooting guide,
and role documentation as structured data.
"""

from __future__ import annotations

from typing import Any

# PRD Section 43.6: Quickstart guide
QUICKSTART_STEPS = [
    {
        "step": 1,
        "title": "Upload your swipe corpus",
        "description": (
            "Upload the DOCX file with creator post examples. "
            "Go to Documents > Upload and select your file. "
            "Optionally enable auto_analyze to trigger parsing."
        ),
        "endpoint": "POST /api/v1/documents/upload",
    },
    {
        "step": 2,
        "title": "Review parsed examples",
        "description": (
            "After parsing, review the extracted post examples. "
            "Check confidence tags (A/B/C) and fix any issues. "
            "Low-confidence examples can be excluded."
        ),
        "endpoint": "GET /api/v1/documents/{id}/examples",
    },
    {
        "step": 3,
        "title": "Check seed data",
        "description": (
            "Verify that 5 creator profiles and 10 templates "
            "are loaded. These are seeded automatically on startup."
        ),
        "endpoint": "GET /api/v1/profiles/creators",
    },
    {
        "step": 4,
        "title": "Plan your week",
        "description": (
            "Generate a 5-day content calendar for the next week. "
            "Review and adjust topics as needed."
        ),
        "endpoint": "POST /api/v1/calendar/plan-week",
    },
    {
        "step": 5,
        "title": "Run the daily pipeline",
        "description": (
            "Trigger the daily content generation pipeline. "
            "This produces FB + LI posts, CTA, image prompts, "
            "and a QA scorecard."
        ),
        "endpoint": "POST /api/v1/pipeline/run",
    },
    {
        "step": 6,
        "title": "Review and approve",
        "description": (
            "Review the generated package in the draft queue. "
            "Check the QA scorecard. Approve or reject with "
            "feedback tags."
        ),
        "endpoint": "GET /api/v1/content/packages",
    },
    {
        "step": 7,
        "title": "Export and publish",
        "description": (
            "Export the approved package for manual publishing. "
            "Copy FB post to Facebook, LI post to LinkedIn. "
            "Set up the CTA keyword DM flow."
        ),
        "endpoint": "POST /api/v1/content/packages/{id}/export",
    },
]

# PRD Section 43.6: Concept glossary
GLOSSARY = {
    "house_voice": (
        "A blend of structural techniques from 5 source creators "
        "(Omri's curiosity + Ben's structure + Nathan's edge + "
        "Eden's practicality + Alex's depth). Controls HOW content "
        "sounds structurally."
    ),
    "founder_voice": (
        "The operator's authentic voice extracted from their books "
        "and writing. Controls WHO the content sounds like. "
        "Takes priority over house voice."
    ),
    "influence_weights": (
        "Numeric weights (0.0-1.0) controlling how much each source "
        "creator's structural patterns influence the output. "
        "Adjustable per angle type."
    ),
    "template_families": (
        "10 reusable post structures: Big Shift Explainer, "
        "Contrarian Diagnosis, Tactical Workflow Guide, etc. "
        "Each maps to a day in the Mon-Fri cadence."
    ),
    "confidence_tags": (
        "A/B/C quality markers on corpus examples. "
        "A = both shares and comments visible. "
        "B = one metric visible. C = unclear/cropped."
    ),
    "engagement_score": (
        "Formula: (shares * 3.0) + (comments * 1.0) * confidence_multiplier. "
        "Used to rank posts and templates."
    ),
    "qa_scorecard": (
        "12-dimension quality check with weighted composite score. "
        "Must score >= 7.0 composite with no dimension below threshold. "
        "Humanitarian sensitivity and CTA honesty are hard gates."
    ),
    "pipeline_run": (
        "A single execution of the agent workflow. Produces a "
        "PostPackage with FB/LI posts, CTA, image prompts, and "
        "QA scorecard. Tracked by run_id."
    ),
    "cta_keyword": (
        "A single word the audience comments to trigger a DM. "
        "One primary keyword per week maps to the weekly guide."
    ),
    "weekly_guide": (
        "A polished DOCX guide serving as the shared lead magnet "
        "across all 5 posts in a week. Delivered via CTA keyword."
    ),
    "post_package": (
        "The complete daily output: FB post, LI post, 5+ hook "
        "variants, CTA keyword + DM flow, 3 image prompts, "
        "and QA scorecard."
    ),
    "learning_loop": (
        "Weekly analysis comparing predicted vs actual engagement. "
        "Updates template priors, CTA rankings, and voice weights."
    ),
}

# PRD Section 43.6: Troubleshooting guide
TROUBLESHOOTING = [
    {
        "issue": "QA keeps failing",
        "possible_causes": [
            "Evidence is stale (freshness check failing)",
            "Posts too similar to source corpus (non-cloning check)",
            "CTA keyword not set up (CTA honesty check)",
        ],
        "resolution": (
            "Check the QA scorecard for the specific dimension that "
            "failed. Address the root cause — usually evidence or "
            "template diversity."
        ),
    },
    {
        "issue": "Rate limit errors",
        "possible_causes": [
            "Too many LLM calls in quick succession",
            "API key quota exceeded",
        ],
        "resolution": (
            "Check /api/v1/scheduler/status for rate limit state. "
            "The system auto-retries with exponential backoff. "
            "If persistent, check your API key quota."
        ),
    },
    {
        "issue": "Budget alerts",
        "possible_causes": [
            "Unusually long posts triggering high token usage",
            "Multiple pipeline re-runs after rejections",
            "Cache hit rate dropped (prompts changing too often)",
        ],
        "resolution": (
            "Check /api/v1/costs/daily for spend breakdown by agent. "
            "Consider downgrading non-critical agents to cheaper models."
        ),
    },
    {
        "issue": "No content generated",
        "possible_causes": [
            "No calendar entry for today",
            "Pipeline not triggered",
            "Missing API key",
        ],
        "resolution": (
            "Check /api/v1/calendar/today for schedule. "
            "Verify pipeline status at /api/v1/pipeline/{run_id}/status. "
            "Ensure ANTHROPIC_API_KEY is set."
        ),
    },
]

# Role documentation (PRD Section 43.6)
ROLE_DOCUMENTATION = {
    "operator_responsibilities": [
        "Review and approve daily post packages",
        "Set up CTA fulfillment (guide link, DM template)",
        "Enter post performance metrics weekly",
        "Review weekly learning recommendations",
        "Override topics when needed via chatbot",
        "Upload new corpus examples periodically",
        "Monitor budget and costs",
    ],
    "system_handles_automatically": [
        "Trend scanning and story selection",
        "Research and claim verification",
        "Draft generation (FB + LI)",
        "CTA keyword and DM flow generation",
        "Image prompt creation",
        "QA scoring on 12 dimensions",
        "Cost tracking per agent per run",
        "Template performance tracking",
        "Weekly learning analysis",
    ],
}


class OnboardingService:
    """Provides onboarding content for new operators."""

    @staticmethod
    def get_quickstart() -> list[dict[str, Any]]:
        return QUICKSTART_STEPS

    @staticmethod
    def get_glossary() -> dict[str, str]:
        return GLOSSARY

    @staticmethod
    def get_troubleshooting() -> list[dict[str, Any]]:
        return TROUBLESHOOTING

    @staticmethod
    def get_role_documentation() -> dict[str, list[str]]:
        return ROLE_DOCUMENTATION

    @staticmethod
    def get_full_onboarding() -> dict[str, Any]:
        return {
            "quickstart": QUICKSTART_STEPS,
            "glossary": GLOSSARY,
            "troubleshooting": TROUBLESHOOTING,
            "roles": ROLE_DOCUMENTATION,
        }
