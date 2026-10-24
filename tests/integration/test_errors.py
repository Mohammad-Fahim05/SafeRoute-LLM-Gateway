"""Integration tests for validation errors, timeouts, provider failures, and safe error normalization."""

from unittest.mock import patch
from starlette.testclient import TestClient


def test_empty_messages_rejected(client: TestClient):
    """Requirement 4: Empty messages list is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
    assert "messages" in data["error"]["message"].lower()
    assert "request_id" in data["error"]


def test_whitespace_message_content_rejected(client: TestClient):
    """Requirement 4: Whitespace-only message content is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "   "}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"


def test_unsupported_fields_rejected(client: TestClient):
    """Requirement 5: Unsupported fields are rejected with 400 unsupported_parameter."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "unsupported_extra_field": "value",
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["type"] == "invalid_request_error"
    assert data["error"]["code"] == "unsupported_parameter"
    assert "unsupported_extra_field" in data["error"]["message"]


def test_unsupported_role_rejected(client: TestClient):
    """Requirement 6: Unsupported role is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "tool", "content": "some tool output"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"


def test_non_text_content_rejected(client: TestClient):
    """Requirement 6: Non-text multimodal content is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": "https://example.com/test.jpg"}],
            }
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"


def test_invalid_model_rejected(client: TestClient):
    """Requirement 7: Model not in allowlist is rejected with 400 invalid_model."""
    payload = {
        "model": "unapproved-gpt-4",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "invalid_model"
    assert "unapproved-gpt-4" in data["error"]["message"]


def test_invalid_temperature_rejected(client: TestClient):
    """Requirement 8: Temperature outside 0-2 is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 3.5,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"


def test_invalid_token_limits_rejected(client: TestClient):
    """Requirement 8: Non-positive max_completion_tokens is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_completion_tokens": -10,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"


def test_token_limit_exceeding_system_max_rejected(client: TestClient):
    """Requirement 8: max_completion_tokens exceeding system limit is rejected with 422."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_completion_tokens": 9999999,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "validation_error"
    assert "exceeds" in data["error"]["message"].lower()


def test_streaming_requests_rejected(client: TestClient):
    """Requirement 9: stream=True is rejected with 400 unsupported_parameter."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["type"] == "invalid_request_error"
    assert data["error"]["code"] == "unsupported_parameter"
    assert "streaming" in data["error"]["message"].lower()


def test_request_id_present_in_error_responses(client: TestClient):
    """Requirement 10: Request IDs are returned in response headers and error payload."""
    payload = {"model": "non-existent-model", "messages": [{"role": "user", "content": "Hi"}]}
    response = client.post("/v1/chat/completions", json=payload)
    assert "X-Request-ID" in response.headers
    data = response.json()
    assert data["error"]["request_id"] == response.headers["X-Request-ID"]


def test_mock_provider_timeout_returns_504(client: TestClient):
    """Requirement 11: Provider timeout returns controlled HTTP 504 error."""
    payload = {
        "model": "mock-timeout",
        "messages": [{"role": "user", "content": "This should time out"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 504
    data = response.json()
    assert data["error"]["type"] == "gateway_timeout_error"
    assert data["error"]["code"] == "gateway_timeout"
    assert "timed out" in data["error"]["message"]


def test_mock_provider_malformed_returns_502(client: TestClient):
    """Requirement 12: Malformed provider output returns controlled HTTP 502 error."""
    payload = {
        "model": "mock-malformed",
        "messages": [{"role": "user", "content": "Trigger malformed"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 502
    data = response.json()
    assert data["error"]["type"] == "bad_gateway_error"
    assert data["error"]["code"] == "provider_malformed_response"


def test_mock_provider_outage_returns_502(client: TestClient):
    """Provider outage returns controlled HTTP 502 error."""
    payload = {
        "model": "mock-error",
        "messages": [{"role": "user", "content": "Trigger 502"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 502
    data = response.json()
    assert data["error"]["type"] == "bad_gateway_error"
    assert data["error"]["code"] == "provider_error"


def test_internal_exception_does_not_leak_stack_traces_or_secrets(client: TestClient):
    """Requirement 13: Unhandled internal errors return safe 500 without leaking stack traces or secrets."""
    secret_internal_token = "SECRET_DATABASE_KEY_998877"

    with patch(
        "app.providers.mock.MockProvider.complete",
        side_effect=Exception(f"Internal crash with secret {secret_internal_token}"),
    ):
        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Crash trigger"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "internal_server_error"
        assert data["error"]["code"] == "internal_error"
        assert data["error"]["message"] == "An internal server error occurred."
        # Verify secret token is NOT leaked in response
        assert secret_internal_token not in response.text
        # Verify stack trace is NOT leaked in response
        assert "Traceback" not in response.text
        assert "line" not in response.text


def test_message_limit_exceeded_rejected(client: TestClient):
    """Ensure message count exceeding limit is rejected with 400."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": f"msg {i}"} for i in range(15)],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "message_limit_exceeded"


def test_payload_too_large_rejected(client: TestClient):
    """Ensure payloads exceeding max_request_size_bytes return HTTP 413."""
    response = client.post(
        "/v1/chat/completions",
        content="x" * 100,
        headers={"Content-Length": "2000000"},  # exceeds 1MB fixture
    )
    assert response.status_code == 413
    data = response.json()
    assert data["error"]["code"] == "payload_too_large"
