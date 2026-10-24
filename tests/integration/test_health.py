"""Integration tests for health and readiness endpoints."""

from unittest.mock import patch
from starlette.testclient import TestClient


def test_health_endpoint_success(client: TestClient):
    """Verify /health returns 200 OK and expected status payload."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "SafeRoute LLM Gateway"
    assert "environment" in data
    assert "X-Request-ID" in response.headers


def test_ready_endpoint_success(client: TestClient):
    """Verify /ready reports ready when providers are operational."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["providers"]["mock"] == "available"


def test_ready_endpoint_failure(client: TestClient):
    """Verify /ready accurately reports 503 when provider health check fails."""
    with patch("app.providers.mock.MockProvider.check_health", return_value=False):
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["providers"]["mock"] == "unavailable"
