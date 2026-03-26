"""API route registration tests — verify all routers are mounted."""

from fastapi.testclient import TestClient

from tce.api.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_pipeline_workflows_endpoint():
    """GET /pipeline/workflows should return available workflows."""
    response = client.get("/api/v1/pipeline/workflows")
    assert response.status_code == 200
    data = response.json()
    assert "daily_content" in data
    assert "corpus_ingestion" in data
    assert "weekly_planning" in data
    assert "founder_voice_extraction" in data


def test_scheduler_status_endpoint():
    """GET /scheduler/status should return job info."""
    response = client.get("/api/v1/scheduler/status")
    assert response.status_code == 200
    data = response.json()
    assert "jobs" in data
    assert "daily_content" in data["jobs"]


def test_onboarding_quickstart_endpoint():
    """GET /onboarding/quickstart should return 7 steps."""
    response = client.get("/api/v1/onboarding/quickstart")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 7


def test_onboarding_glossary_endpoint():
    response = client.get("/api/v1/onboarding/glossary")
    assert response.status_code == 200
    data = response.json()
    assert "house_voice" in data
    assert "founder_voice" in data


def test_experiments_types_endpoint():
    response = client.get("/api/v1/experiments/types/available")
    assert response.status_code == 200
    data = response.json()
    assert "experiment_types" in data
    assert "hook_variant" in data["experiment_types"]


def test_chat_endpoint():
    """POST /chat should accept messages."""
    response = client.post(
        "/api/v1/chat",
        json={"message": "help"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "help"
    assert data["success"] is True


def test_chat_unknown_intent():
    response = client.post(
        "/api/v1/chat",
        json={"message": "xyzzy"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "unknown"


def test_platforms_endpoint():
    response = client.get("/api/v1/controls/platforms")
    assert response.status_code == 200
    data = response.json()
    assert "facebook" in data
    assert "linkedin" in data


def test_dm_fulfillment_pending_count():
    """GET /dm-fulfillment/pending/count should work."""
    response = client.get("/api/v1/dm-fulfillment/pending/count")
    # May fail without DB but should at least route correctly
    assert response.status_code in (200, 500)


def test_notifications_count():
    response = client.get("/api/v1/notifications/count")
    assert response.status_code in (200, 500)
