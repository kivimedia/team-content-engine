"""Tests for notification system (PRD Section 43.1)."""

from tce.services.notifications import NotificationService


def test_service_exists():
    assert NotificationService is not None


def test_service_has_notify_methods():
    """All notification convenience methods should exist."""
    methods = [
        "notify",
        "package_ready",
        "qa_failure",
        "budget_alert",
        "corpus_parsed",
        "model_fallback",
        "weekly_update_ready",
        "get_unread",
        "get_unread_count",
        "mark_read",
        "mark_all_read",
    ]
    for method in methods:
        assert hasattr(NotificationService, method), f"Missing method: {method}"


def test_notify_methods_are_async():
    import asyncio

    for method in [
        "notify",
        "package_ready",
        "qa_failure",
        "budget_alert",
        "get_unread",
        "get_unread_count",
        "mark_read",
        "mark_all_read",
    ]:
        fn = getattr(NotificationService, method)
        assert asyncio.iscoroutinefunction(fn), f"{method} should be async"
