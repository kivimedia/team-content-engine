"""Worked example — PRD Appendix D as a test fixture.

This test verifies the complete Monday PostPackage structure
from the PRD's worked example, ensuring all expected fields
and values are representable in our data model.
"""

from tce.schemas.common import QA_DIMENSIONS, QA_THRESHOLDS, QA_WEIGHTS

# PRD Appendix D: Complete Monday PostPackage
WORKED_EXAMPLE = {
    "story_brief": {
        "brief_id": "WK12-MON-001",
        "topic": ("Autonomous AI agent teams — Claude's new multi-agent coordination"),
        "audience": (
            "Business professionals and founders who use AI tools "
            "daily but haven't grasped the agent paradigm shift"
        ),
        "angle_type": "big_shift_explainer",
        "desired_belief_shift": (
            "FROM: 'AI is a smarter chatbot I type into' -> "
            "TO: 'AI is becoming a workforce that coordinates without me'"
        ),
        "template_id": "big_shift_explainer",
        "house_voice_weights": {
            "omri": 0.30,
            "alex": 0.30,
            "nathan": 0.20,
            "ben": 0.15,
            "eden": 0.05,
        },
        "thesis": (
            "The real shift isn't that AI got smarter — it's that "
            "AI agents can now delegate to other AI agents."
        ),
        "evidence_requirements": [
            "Anthropic announcement details",
            "agent team architecture",
            "at least one concrete use case",
            "cost/token data if available",
        ],
        "cta_goal": "weekly_guide_keyword",
        "visual_job": "cinematic_symbolic",
    },
    "research_brief": {
        "verified_claims": [
            {
                "claim": "Anthropic released agent teams feature",
                "source": "Anthropic blog",
                "confidence": "verified",
            },
        ],
        "uncertain_claims": [
            {
                "claim": "Average cost of $6/developer/day",
                "confidence": "uncertain",
            },
        ],
        "rejected_claims": [
            {
                "claim": "Agent teams can autonomously deploy",
                "reason": "Not supported",
            },
        ],
        "safe_to_publish": True,
    },
    "cta_package": {
        "weekly_keyword": "agents",
        "fb_cta_line": ('Comment "agents" and I\'ll send it to you.'),
        "dm_flow": {
            "trigger": "agents",
            "ack_message": "Hey! Thanks for commenting.",
        },
    },
    "qa_scorecard": {
        "evidence_completeness": 9,
        "freshness": 9,
        "clarity": 8,
        "novelty": 8,
        "non_cloning": 9,
        "audience_fit": 8,
        "cta_honesty": 10,
        "platform_fit": 9,
        "visual_coherence": 8,
        "house_voice_fit": 8,
        "humanitarian_sensitivity": 9,
        "founder_voice_alignment": 7,
    },
}


def test_worked_example_has_all_story_brief_fields():
    """Story brief must have all required fields."""
    brief = WORKED_EXAMPLE["story_brief"]
    required = [
        "brief_id",
        "topic",
        "audience",
        "angle_type",
        "desired_belief_shift",
        "template_id",
        "house_voice_weights",
        "thesis",
        "evidence_requirements",
        "cta_goal",
        "visual_job",
    ]
    for field in required:
        assert field in brief, f"Missing: {field}"


def test_worked_example_voice_weights_sum():
    weights = WORKED_EXAMPLE["story_brief"]["house_voice_weights"]
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01


def test_worked_example_has_research_brief():
    brief = WORKED_EXAMPLE["research_brief"]
    assert len(brief["verified_claims"]) >= 1
    assert brief["safe_to_publish"] is True


def test_worked_example_has_rejected_claims():
    """Research must track rejected claims."""
    brief = WORKED_EXAMPLE["research_brief"]
    assert len(brief["rejected_claims"]) >= 1


def test_worked_example_cta():
    cta = WORKED_EXAMPLE["cta_package"]
    assert cta["weekly_keyword"] == "agents"
    assert "agents" in cta["fb_cta_line"]


def test_worked_example_qa_all_dimensions():
    """QA scorecard must have all 12 dimensions."""
    qa = WORKED_EXAMPLE["qa_scorecard"]
    for dim in QA_DIMENSIONS:
        assert dim in qa, f"Missing QA dimension: {dim}"


def test_worked_example_qa_all_pass():
    """The worked example should pass all QA gates."""
    qa = WORKED_EXAMPLE["qa_scorecard"]
    for dim in QA_DIMENSIONS:
        threshold = QA_THRESHOLDS[dim]
        assert qa[dim] >= threshold, f"{dim}: {qa[dim]} < threshold {threshold}"


def test_worked_example_composite_score():
    """Composite score should be >= 7.0."""
    qa = WORKED_EXAMPLE["qa_scorecard"]
    composite = sum(qa[dim] * QA_WEIGHTS[dim] for dim in QA_DIMENSIONS)
    assert composite >= 7.0, f"Composite {composite} < 7.0"


def test_worked_example_humanitarian_hard_gate():
    """Humanitarian sensitivity must be >= 8."""
    assert WORKED_EXAMPLE["qa_scorecard"]["humanitarian_sensitivity"] >= 8


def test_worked_example_cta_honesty_hard_gate():
    """CTA honesty must be >= 9."""
    assert WORKED_EXAMPLE["qa_scorecard"]["cta_honesty"] >= 9
