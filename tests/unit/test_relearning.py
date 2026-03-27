"""Tests for corpus relearning logic (PRD Section 48)."""

from tce.services.relearning import (
    MAX_INFLUENCE_WEIGHT_DROP,
    MAX_TEMPLATE_SCORE_DROP,
    MIN_CONFIDENCE_B_RATIO,
    MIN_EXAMPLES_FOR_ADMISSION,
    RelearningService,
    RelearningTrigger,
)


def test_trigger_types():
    assert RelearningTrigger.A == "more_examples_existing_creator"
    assert RelearningTrigger.B == "new_creator"
    assert RelearningTrigger.C == "new_template_discovered"


def test_admission_thresholds():
    """PRD Section 16.2 thresholds."""
    assert MIN_EXAMPLES_FOR_ADMISSION == 5
    assert MIN_CONFIDENCE_B_RATIO == 0.5


def test_regression_threshold():
    """PRD Section 48.6: 15% score drop triggers review."""
    assert MAX_TEMPLATE_SCORE_DROP == 0.15


def test_influence_weight_threshold():
    """PRD Section 48.6: 0.05 weight drop triggers review."""
    assert MAX_INFLUENCE_WEIGHT_DROP == 0.05


def test_relearning_service_exists():
    assert RelearningService is not None


def test_service_has_required_methods():
    """All relearning methods should exist."""
    methods = [
        "detect_trigger",
        "evaluate_new_creator",
        "check_template_regression",
        "check_influence_weight_impact",
        "get_relearning_summary",
    ]
    for method in methods:
        assert hasattr(RelearningService, method), f"Missing method: {method}"


def test_service_methods_are_async():
    import asyncio

    for method in [
        "detect_trigger",
        "evaluate_new_creator",
        "check_template_regression",
        "check_influence_weight_impact",
        "get_relearning_summary",
    ]:
        fn = getattr(RelearningService, method)
        assert asyncio.iscoroutinefunction(fn), f"{method} should be async"
