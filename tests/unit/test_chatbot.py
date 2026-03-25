"""Tests for chatbot intent classification."""

from tce.services.chatbot import ChatbotService, classify_intent


def test_classify_today():
    assert classify_intent("What's today's post?") == "query_today"
    assert classify_intent("what's scheduled today") == "query_today"


def test_classify_week():
    assert classify_intent("What's this week's plan") == "query_week"
    assert classify_intent("what's queued for the week") == "query_week"


def test_classify_costs():
    assert classify_intent("How much have we spent?") == "query_costs"
    assert classify_intent("Show me the budget") == "query_costs"


def test_classify_performance():
    assert classify_intent("What's the best performing CTA?") == "query_performance"
    assert classify_intent("which template worked") == "query_performance"


def test_classify_trigger():
    assert classify_intent("Run the daily pipeline") == "trigger_pipeline"
    assert classify_intent("Generate today's post") == "trigger_pipeline"


def test_classify_skip():
    assert classify_intent("Skip today") == "skip_day"
    assert classify_intent("Cancel today's post") == "skip_day"


def test_classify_override():
    assert classify_intent("Write about OpenAI's new model") == "override_topic"
    assert classify_intent("Change topic to AI agents") == "override_topic"


def test_classify_approve():
    assert classify_intent("Approve it") == "approve"
    assert classify_intent("Looks good, ship it") == "approve"


def test_classify_reject():
    assert classify_intent("Reject this one") == "reject"
    assert classify_intent("Try again") == "reject"


def test_classify_status():
    assert classify_intent("What's the pipeline status?") == "status"


def test_classify_help():
    assert classify_intent("Help me") == "help"
    assert classify_intent("What can you do?") == "help"


def test_classify_unknown():
    assert classify_intent("asdfghjkl") == "unknown"
    assert classify_intent("") == "unknown"


def test_chatbot_service_exists():
    assert ChatbotService is not None


def test_chatbot_has_handle_message():
    import asyncio

    assert hasattr(ChatbotService, "handle_message")
    assert asyncio.iscoroutinefunction(ChatbotService.handle_message)
