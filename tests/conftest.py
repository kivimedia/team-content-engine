"""Shared test fixtures."""

import os
from urllib.parse import urlsplit

import pytest

# --- Never the live box (integrated review, 5-Oct) -------------------------------
# On the VPS the settings defaults ARE the live services: the default database URL
# reaches the live TCE database on this box, :8200 is the live API, and
# /home/ziv/skills holds the schedule-* CLIs that post to the owner's real accounts.
# Every one is pointed at a dead address here, before any tce module is imported
# (environment variables win over a .env file in pydantic-settings), and a run that
# is pointed at the live database anyway refuses to start.
_DEAD = {
    "TCE_DATABASE_URL": "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/tce_test_never",
    "TCE_REDIS_URL": "redis://127.0.0.1:1/15",
    "TCE_PRODUCTION_SELF_URL": "http://127.0.0.1:1",
    "TCE_CUTSENSE_API_URL": "http://127.0.0.1:1",
    "TCE_PRODUCTION_SKILLS_DIR": "/nonexistent/tce-test-noskills",
    "TCE_PRODUCTION_LINKEDIN_ENV_FILE": "/nonexistent/tce-test-noskills/li.env",
}
for _name, _value in _DEAD.items():
    os.environ.setdefault(_name, _value)


def is_live_database(url: str) -> bool:
    """The live TCE database: database "tce" on this box's Postgres (localhost:5432)."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port or 5432
    except ValueError:
        return False
    if not parts.scheme.startswith("postgres"):
        return False
    return host in ("localhost", "127.0.0.1", "::1") and port == 5432 and parts.path.strip("/") == "tce"


if is_live_database(os.environ["TCE_DATABASE_URL"]):
    raise pytest.UsageError(
        "TCE_DATABASE_URL points at the live TCE database; the test suite never runs against it"
    )

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
