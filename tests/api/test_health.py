"""API tests for health endpoint using FastAPI TestClient."""

from fastapi.testclient import TestClient

from tce.api.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_health_endpoint_returns_200():
    """Health endpoint should return 200 even without DB."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "version" in data


def test_health_includes_version():
    response = client.get("/api/v1/health")
    data = response.json()
    assert data["version"] == "0.1.0"
