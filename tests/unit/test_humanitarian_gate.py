"""Tests for humanitarian sensitivity gate (PRD Section 51)."""

from tce.services.humanitarian_gate import (
    ACTUAL_THRESHOLD,
    CANNOT_BE_DISABLED,
    FLAG_PATTERNS,
    MIN_THRESHOLD,
    MIN_WEIGHT,
    HumanitarianGate,
)


def test_non_negotiable_constraints():
    """PRD Section 51.6: cannot be disabled or set below minimums."""
    assert MIN_WEIGHT >= 0.08
    assert MIN_THRESHOLD >= 7
    assert ACTUAL_THRESHOLD == 8
    assert CANNOT_BE_DISABLED is True


def test_flag_patterns_exist():
    """At least 5 flag patterns per PRD Section 51.4."""
    assert len(FLAG_PATTERNS) >= 5


def test_clean_content_passes():
    gate = HumanitarianGate()
    result = gate.check(
        facebook_post="AI tools can help you work smarter.",
        linkedin_post="Here's how teams are using AI effectively.",
    )
    assert result["passes"]
    assert result["score"] >= 8


def test_fear_exploitation_flagged():
    gate = HumanitarianGate()
    result = gate.check(
        facebook_post="There's nothing you can do about AI replacing you.",
    )
    assert not result["passes"]
    assert len(result["flags"]) > 0
    assert any(f["pattern"] == "fear_exploitation" for f in result["flags"])


def test_war_metaphors_flagged():
    gate = HumanitarianGate()
    result = gate.check(
        facebook_post="This tool is a weapon for your business.",
    )
    assert len(result["flags"]) > 0


def test_sensitive_period_penalty():
    """Sensitive period should lower the score."""
    gate_normal = HumanitarianGate(sensitive_period=False)
    gate_sensitive = HumanitarianGate(sensitive_period=True)

    post = "A simple guide to AI automation."
    normal = gate_normal.check(facebook_post=post)
    sensitive = gate_sensitive.check(facebook_post=post)

    assert sensitive["score"] <= normal["score"]


def test_validate_config_valid():
    result = HumanitarianGate.validate_config(weight=0.10, threshold=8)
    assert result["valid"]


def test_validate_config_below_minimum():
    result = HumanitarianGate.validate_config(weight=0.05, threshold=5)
    assert not result["valid"]
    assert result["enforced_weight"] == MIN_WEIGHT
    assert result["enforced_threshold"] == MIN_THRESHOLD


def test_punishment_framing_flagged():
    gate = HumanitarianGate()
    result = gate.check(
        facebook_post="You're doing it wrong and it's your fault.",
    )
    assert len(result["flags"]) > 0
