"""Tests for QA scoring logic."""

from tce.schemas.common import QA_DIMENSIONS, QA_THRESHOLDS, QA_WEIGHTS


def test_dimensions_count():
    """PRD specifies 12 QA dimensions."""
    assert len(QA_DIMENSIONS) == 12


def test_weights_sum_to_one():
    """All dimension weights should sum to 1.0."""
    total = sum(QA_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001


def test_all_dimensions_have_weights():
    """Every dimension must have a weight."""
    for dim in QA_DIMENSIONS:
        assert dim in QA_WEIGHTS, f"Missing weight for {dim}"


def test_all_dimensions_have_thresholds():
    """Every dimension must have a pass threshold."""
    for dim in QA_DIMENSIONS:
        assert dim in QA_THRESHOLDS, f"Missing threshold for {dim}"


def test_humanitarian_sensitivity_floor():
    """PRD Section 51.6: humanitarian sensitivity cannot be set below weight 8%."""
    assert QA_WEIGHTS["humanitarian_sensitivity"] >= 0.08


def test_humanitarian_sensitivity_threshold():
    """PRD Section 51.6: pass threshold cannot be set below 7."""
    assert QA_THRESHOLDS["humanitarian_sensitivity"] >= 7


def test_cta_honesty_high_threshold():
    """CTA honesty has the highest threshold at 9."""
    assert QA_THRESHOLDS["cta_honesty"] == 9
