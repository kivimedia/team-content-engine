"""Tests for PromptManager service."""

from tce.services.prompt_manager import PromptManager


def test_service_exists():
    assert PromptManager is not None


def test_has_crud_methods():
    import asyncio

    methods = [
        "get_active",
        "create_version",
        "rollback",
        "list_versions",
    ]
    for method in methods:
        assert hasattr(PromptManager, method), f"Missing: {method}"
        assert asyncio.iscoroutinefunction(getattr(PromptManager, method)), f"{method} not async"
