"""Tests for ScriptAgent - style selection and segment parsing."""

from tce.agents.script_agent import (
    _has_before_after,
    _has_stats,
    _has_steps,
    _select_style,
)


def test_select_style_hook_cta_default():
    """Empty context falls back to hook_cta."""
    assert _select_style({}) == "hook_cta"


def test_select_style_hook_cta_with_thesis():
    """Thesis-only context selects hook_cta."""
    ctx = {"story_brief": {"thesis": "AI changes everything"}}
    assert _select_style(ctx) == "hook_cta"


def test_select_style_stat_heavy():
    """Context with verified claims selects stat_heavy."""
    ctx = {"research_brief": {"verified_claims": [{"claim": "73% of agencies"}]}}
    assert _select_style(ctx) == "stat_heavy"


def test_select_style_before_after():
    """Context with belief shift selects before_after."""
    ctx = {"story_brief": {"desired_belief_shift": "manual -> automated"}}
    assert _select_style(ctx) == "before_after"


def test_select_style_step_framework():
    """Context with steps selects step_framework."""
    ctx = {"guide_sections": [{"steps": ["step1", "step2", "step3"]}]}
    assert _select_style(ctx) == "step_framework"


def test_select_style_mixed():
    """Context with thesis + stats + belief shift selects mixed."""
    ctx = {
        "story_brief": {
            "thesis": "AI changes everything",
            "desired_belief_shift": "old -> new",
        },
        "research_brief": {"verified_claims": [{"claim": "data"}]},
    }
    assert _select_style(ctx) == "mixed"


def test_has_stats_true():
    assert _has_stats({"research_brief": {"verified_claims": [{"x": 1}]}})


def test_has_stats_false():
    assert not _has_stats({})
    assert not _has_stats({"research_brief": {"verified_claims": []}})


def test_has_before_after_true():
    assert _has_before_after({"story_brief": {"desired_belief_shift": "A -> B"}})


def test_has_before_after_false():
    assert not _has_before_after({"story_brief": {"desired_belief_shift": "no arrow"}})


def test_has_steps_with_guide_sections():
    ctx = {"guide_sections": [{"steps": ["a", "b"]}]}
    assert _has_steps(ctx)


def test_has_steps_with_key_findings():
    ctx = {"research_brief": {"key_findings": ["a", "b", "c"]}}
    assert _has_steps(ctx)


def test_has_steps_false():
    assert not _has_steps({})
