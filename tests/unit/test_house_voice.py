"""Tests for house voice system (PRD Section 14)."""

from tce.services.house_voice import (
    ANGLE_WEIGHT_OVERRIDES,
    DEFAULT_INFLUENCE_WEIGHTS,
    SIMILARITY_THRESHOLD,
    VOICE_AXES,
    HouseVoiceEngine,
)


def test_ten_voice_axes():
    """PRD Section 14.1: 10 voice axes."""
    assert len(VOICE_AXES) == 10
    expected = {
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
    assert set(VOICE_AXES) == expected


def test_default_weights_sum():
    """Default influence weights should sum to 1.0."""
    total = sum(DEFAULT_INFLUENCE_WEIGHTS.values())
    assert abs(total - 1.0) < 0.01


def test_default_weights_five_creators():
    """Five creators in default weights."""
    assert len(DEFAULT_INFLUENCE_WEIGHTS) == 5


def test_angle_overrides_exist():
    """Per-angle weight overrides should exist."""
    assert "weekly_roundup" in ANGLE_WEIGHT_OVERRIDES
    assert "tactical_workflow_guide" in ANGLE_WEIGHT_OVERRIDES
    assert "contrarian_diagnosis" in ANGLE_WEIGHT_OVERRIDES
    assert "founder_reflection" in ANGLE_WEIGHT_OVERRIDES


def test_angle_override_weights_sum():
    """Each angle override should sum to ~1.0."""
    for angle, weights in ANGLE_WEIGHT_OVERRIDES.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"{angle} weights sum to {total}"


def test_similarity_threshold():
    """PRD Section 14.3: anti-clone similarity threshold."""
    assert SIMILARITY_THRESHOLD == 0.85


def test_get_weights_default():
    engine = HouseVoiceEngine()
    weights = engine.get_weights_for_angle("big_shift_explainer")
    assert weights == DEFAULT_INFLUENCE_WEIGHTS


def test_get_weights_angle_override():
    engine = HouseVoiceEngine()
    weights = engine.get_weights_for_angle("weekly_roundup")
    assert weights == ANGLE_WEIGHT_OVERRIDES["weekly_roundup"]


def test_get_weights_operator_override():
    engine = HouseVoiceEngine()
    overrides = {"Omri Barak": 0.5, "Alex Kap": 0.5}
    weights = engine.get_weights_for_angle("big_shift_explainer", overrides)
    assert weights["Omri Barak"] == 0.5
    assert weights["Alex Kap"] == 0.5


def test_blend_voice_axes():
    """Blending should produce weighted averages."""
    profiles = {
        "A": {"voice_axes": {"curiosity": 10, "sharpness": 0}},
        "B": {"voice_axes": {"curiosity": 0, "sharpness": 10}},
    }
    engine = HouseVoiceEngine(creator_profiles=profiles)
    blended = engine.blend_voice_axes({"A": 0.5, "B": 0.5})
    assert blended["curiosity"] == 5.0
    assert blended["sharpness"] == 5.0


def test_build_voice_prompt():
    """Voice prompt should contain key sections."""
    engine = HouseVoiceEngine()
    prompt = engine.build_voice_prompt("big_shift_explainer")
    assert "[HOUSE VOICE BLEND]" in prompt
    assert "[ANTI-CLONE CONTROLS]" in prompt
    assert "Influence weights:" in prompt


def test_build_voice_prompt_with_founder():
    """Voice prompt should include founder voice when available."""
    engine = HouseVoiceEngine(
        founder_voice={
            "values_and_beliefs": ["authenticity", "depth"],
            "taboos": ["hype", "fake urgency"],
            "recurring_themes": ["AI ethics"],
        }
    )
    prompt = engine.build_voice_prompt("big_shift_explainer")
    assert "[FOUNDER VOICE LAYER]" in prompt
    assert "authenticity" in prompt
    assert "hype" in prompt


def test_normalize_weights():
    result = HouseVoiceEngine._normalize_weights({"A": 2.0, "B": 3.0})
    assert abs(result["A"] - 0.4) < 0.001
    assert abs(result["B"] - 0.6) < 0.001
