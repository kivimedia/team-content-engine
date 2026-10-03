"""Shared test fixtures."""

import pytest

# editorial_session / editorial_sessionmaker fixtures for the new evidence tables
pytest_plugins = ["tests.editorial_db"]


@pytest.fixture(autouse=True)
def jennifer_only_where_asked(monkeypatch):
    """Jennifer's check and her learning are on in production and off in this suite
    unless a test turns them on.

    After every render the check runs ffmpeg meters, asks the local recogniser and waits
    for a subscription job; after every applied note the learning waits for another.
    A test about a render, a sitting or a request would otherwise wait on a worker that
    is not there. The tests about Jennifer (tests/unit/test_jennifer_*.py) switch them
    on and stand in for the worker.
    """
    from tce.settings import settings

    monkeypatch.setattr(settings, "production_qc", "off")
    monkeypatch.setattr(settings, "production_learn_rules", False)


@pytest.fixture
def sample_post_example() -> dict:
    """A sample post example for testing."""
    return {
        "creator_name": "Ben Z. Yabets",
        "post_text_raw": "How do you know if you're a successful consultant?",
        "hook_text": "How do you know if you're a successful consultant or not?",
        "body_text": "Most people will look for experience. There are 3 different things.",
        "cta_text": "Write 'factory' in the comments.",
        "hook_type": "second_person_diagnosis",
        "body_structure": "numbered_framework",
        "story_arc": "diagnosis_to_reframe",
        "tension_type": "curiosity_gap",
        "cta_type": "keyword_comment",
        "visual_type": "screenshot",
        "visible_comments": 89,
        "visible_shares": 32,
        "engagement_confidence": "A",
    }


@pytest.fixture
def sample_story_brief() -> dict:
    """A sample story brief for testing."""
    return {
        "topic": "AI agents can now coordinate autonomously",
        "audience": "Business professionals using AI daily",
        "angle_type": "big_shift_explainer",
        "desired_belief_shift": "FROM: AI is a chatbot -> TO: AI is a team",
        "template_id": "big_shift_explainer",
        "house_voice_weights": {
            "omri": 0.30,
            "alex": 0.30,
            "nathan": 0.20,
            "ben": 0.15,
            "eden": 0.05,
        },
        "thesis": "AI agents can now delegate to other AI agents",
        "evidence_requirements": ["Anthropic announcement", "agent architecture"],
        "cta_goal": "weekly_guide_keyword",
        "visual_job": "cinematic_symbolic",
    }
