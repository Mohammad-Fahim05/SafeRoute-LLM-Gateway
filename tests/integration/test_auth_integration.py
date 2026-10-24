"""Integration tests for Client API-Key Authentication."""

from unittest.mock import patch
from starlette.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import DISABLED_TEST_KEY, VALID_TEST_KEY


def test_missing_authorization_header_returns_401(unauthenticated_client: TestClient):
    """Requirement 1: Requests without Authorization header return HTTP 401."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = unauthenticated_client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    data = response.json()
    assert data["error"]["type"] == "authentication_error"
    assert data["error"]["code"] == "invalid_api_key"
    assert "Missing Authorization" in data["error"]["message"]


def test_malformed_bearer_header_returns_401(unauthenticated_client: TestClient):
    """Requirement 2: Malformed Authorization headers return HTTP 401."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    # Test wrong scheme
    r1 = unauthenticated_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert r1.status_code == 401
    assert "Expected 'Bearer <key>'" in r1.json()["error"]["message"]

    # Test missing token
    r2 = unauthenticated_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer"},
    )
    assert r2.status_code == 401

    # Test whitespace token
    r3 = unauthenticated_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer   "},
    )
    assert r3.status_code == 401


def test_invalid_key_returns_401(unauthenticated_client: TestClient):
    """Requirement 3: Invalid or forged API key returns HTTP 401."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = unauthenticated_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer gw_test_completely_fabricated_key_12345"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["type"] == "authentication_error"
    assert "Invalid client API key" in data["error"]["message"]


def test_revoked_key_returns_401(unauthenticated_client: TestClient):
    """Requirement 4: Disabled or revoked keys return HTTP 401."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = unauthenticated_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {DISABLED_TEST_KEY}"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["type"] == "authentication_error"
    assert "disabled or revoked" in data["error"]["message"].lower()


def test_valid_key_identifies_correct_client(client: TestClient):
    """Requirement 5: Valid key succeeds and processes request."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {VALID_TEST_KEY}"},
    )
    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"


def test_auth_rejection_occurs_before_provider_invocation(unauthenticated_client: TestClient):
    """Requirement 6: Provider complete is NEVER called if authentication fails."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with patch("app.providers.mock.MockProvider.complete") as mock_complete:
        response = unauthenticated_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer gw_test_invalid_key"},
        )
        assert response.status_code == 401
        mock_complete.assert_not_called()


def test_auth_misconfigured_fails_safely():
    """Requirement 7: Missing AUTH_SECRET fails safely without crashing or exposing secrets."""
    bad_settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret="",  # Misconfigured
        client_keys=[],
    )
    app = create_app()
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: bad_settings

    test_c = TestClient(app, raise_server_exceptions=False)
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = test_c.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer gw_test_some_key"},
    )
    assert response.status_code == 401
    assert "misconfigured" in response.json()["error"]["message"]


def test_logs_do_not_contain_plaintext_keys_or_secrets(
    unauthenticated_client: TestClient, capsys
):
    """Requirement 8: Structured logs never expose plaintext keys or secrets."""
    secret_key = "gw_test_super_secret_never_log_this_key_998877"
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    response = unauthenticated_client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {secret_key}"},
    )
    assert response.status_code == 401

    captured = capsys.readouterr()
    # Check stdout and stderr
    assert secret_key not in captured.out
    assert secret_key not in captured.err
    assert "super_secret" not in captured.out


def test_health_and_ready_endpoints_remain_public(unauthenticated_client: TestClient):
    """Verify /health and /ready do not require authentication."""
    r_health = unauthenticated_client.get("/health")
    assert r_health.status_code == 200

    r_ready = unauthenticated_client.get("/ready")
    assert r_ready.status_code == 200
