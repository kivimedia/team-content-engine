"""Tests for PipelineResultSaver logic (dict → ORM mapping)."""

from tce.services.pipeline_saver import PipelineResultSaver


def test_saver_class_exists():
    """PipelineResultSaver should be importable."""
    assert PipelineResultSaver is not None


def test_saver_has_all_save_methods():
    """Saver should have methods for all agent output types."""
    methods = [
        "save_post_examples",
        "save_engagement_scores",
        "save_templates",
        "save_trend_brief",
        "save_story_brief",
        "save_research_brief",
        "save_post_package",
        "save_qa_scorecard",
        "save_weekly_guide",
    ]
    for method in methods:
        assert hasattr(PipelineResultSaver, method), f"Missing method: {method}"


def test_saver_methods_are_async():
    """All save methods should be coroutines."""
    import asyncio

    methods = [
        "save_post_examples",
        "save_engagement_scores",
        "save_templates",
        "save_trend_brief",
        "save_story_brief",
        "save_research_brief",
        "save_post_package",
        "save_qa_scorecard",
        "save_weekly_guide",
    ]
    for method in methods:
        fn = getattr(PipelineResultSaver, method)
        assert asyncio.iscoroutinefunction(fn), f"{method} should be async"
