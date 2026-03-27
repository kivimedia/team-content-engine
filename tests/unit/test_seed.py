"""Tests for seed data definitions."""

from tce.services.seed import (
    DEFAULT_CREATORS,
    DEFAULT_PROMPTS,
    DEFAULT_TEMPLATES,
)


def test_five_default_creators():
    """PRD specifies 5 default creators."""
    assert len(DEFAULT_CREATORS) == 5


def test_creator_names():
    """All 5 creators from the PRD should be present."""
    names = {c["creator_name"] for c in DEFAULT_CREATORS}
    expected = {
        "Omri Barak",
        "Ben Z. Yabets",
        "Nathan Savis",
        "Eden Bibas",
        "Alex Kap",
    }
    assert names == expected


def test_creator_weights_sum():
    """Influence weights should sum to ~1.0."""
    total = sum(c["allowed_influence_weight"] for c in DEFAULT_CREATORS)
    assert abs(total - 1.0) < 0.01


def test_creator_voice_axes():
    """Every creator should have voice axes with 10 dimensions."""
    expected_axes = {
        "curiosity",
        "sharpness",
        "practicality",
        "strategic_depth",
        "emotional_intensity",
        "sentence_punch",
        "executive_clarity",
        "contrarian_heat",
        "friendliness",
        "urgency",
    }
    for creator in DEFAULT_CREATORS:
        axes = creator.get("voice_axes", {})
        assert set(axes.keys()) == expected_axes, f"{creator['creator_name']} missing axes"


def test_ten_default_templates():
    """PRD specifies 10 template families."""
    assert len(DEFAULT_TEMPLATES) == 10


def test_template_families():
    """All template families from the PRD should be present."""
    families = {t["template_family"] for t in DEFAULT_TEMPLATES}
    expected = {
        "big_shift_explainer",
        "tactical_workflow_guide",
        "contrarian_diagnosis",
        "case_study_build_story",
        "second_order_implication",
        "hidden_feature_shortcut",
        "teardown_myth_busting",
        "weekly_roundup",
        "founder_reflection",
        "comment_keyword_cta_guide",
    }
    assert families == expected


def test_templates_have_influence_weights():
    """Each template should have source influence weights."""
    for tpl in DEFAULT_TEMPLATES:
        weights = tpl.get("source_influence_weights", {})
        assert len(weights) >= 2, f"{tpl['template_name']} needs influence weights"


def test_three_default_prompts():
    """Three starter prompts from PRD Appendix E."""
    assert len(DEFAULT_PROMPTS) == 3


def test_prompt_agents():
    """Prompts should cover the 3 key agents."""
    agents = {p["agent_name"] for p in DEFAULT_PROMPTS}
    assert agents == {
        "story_strategist",
        "facebook_writer",
        "qa_agent",
    }
