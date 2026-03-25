"""Tests for A/B testing framework (PRD Section 43.2)."""

from tce.services.ab_testing import (
    DEFAULT_MIN_SAMPLE_SIZE,
    EXPERIMENT_TYPES,
    Experiment,
)


def test_experiment_types():
    """PRD Section 43.2: supported experiment types."""
    assert "hook_variant" in EXPERIMENT_TYPES
    assert "cta_keyword" in EXPERIMENT_TYPES
    assert "visual_direction" in EXPERIMENT_TYPES
    assert "prompt_version" in EXPERIMENT_TYPES


def test_default_min_sample_size():
    """PRD Section 43.2: default 10 posts per variant."""
    assert DEFAULT_MIN_SAMPLE_SIZE == 10


def test_experiment_creation():
    exp = Experiment(
        experiment_id="test_1",
        experiment_type="hook_variant",
        variants=["A", "B"],
    )
    assert exp.experiment_id == "test_1"
    assert exp.variants == ["A", "B"]


def test_deterministic_assignment():
    """PRD Section 43.2: deterministic per run."""
    exp = Experiment(
        experiment_id="test_1",
        experiment_type="hook_variant",
        variants=["A", "B"],
    )
    # Odd days = A (index 1), Even days = B (index 0)
    assert exp.assign_variant(0) == "A"
    assert exp.assign_variant(1) == "B"
    assert exp.assign_variant(2) == "A"
    assert exp.assign_variant(3) == "B"
    # Same day always same result
    assert exp.assign_variant(5) == exp.assign_variant(5)


def test_experiment_to_dict():
    exp = Experiment(
        experiment_id="test_1",
        experiment_type="hook_variant",
        variants=["A", "B"],
    )
    d = exp.to_dict()
    assert d["experiment_id"] == "test_1"
    assert d["experiment_type"] == "hook_variant"
    assert d["variants"] == ["A", "B"]
    assert "min_sample_size" in d
