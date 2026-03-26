"""Tests for learning loop DB updater."""

import asyncio

from tce.services.learning_updater import LearningUpdater


def test_updater_exists():
    assert LearningUpdater is not None


def test_updater_has_methods():
    methods = [
        "update_template_scores",
        "update_template_status",
        "apply_voice_weight_adjustments",
    ]
    for method in methods:
        assert hasattr(LearningUpdater, method), f"Missing: {method}"


def test_methods_are_async():
    for method in [
        "update_template_scores",
        "update_template_status",
        "apply_voice_weight_adjustments",
    ]:
        fn = getattr(LearningUpdater, method)
        assert asyncio.iscoroutinefunction(fn), f"{method} not async"
