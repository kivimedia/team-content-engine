"""Tests for LearningService."""

from tce.services.learning import LearningService


def test_service_exists():
    assert LearningService is not None


def test_has_get_weekly_data():
    import asyncio

    assert hasattr(LearningService, "get_weekly_data")
    assert asyncio.iscoroutinefunction(LearningService.get_weekly_data)
