"""Integration tests for chat completions endpoint."""

from starlette.testclient import TestClient


def test_valid_chat_request_returns_documented_response(client: TestClient):
    """Verify standard chat completion request returns full OpenAI-compatible schema."""
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain what an LLM gateway does."},
        ],
        "temperature": 0.2,
        "max_completion_tokens": 200,
        "stream": False,
    }

    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Verify root fields
    assert data["object"] == "chat.completion"
    assert data["model"] == "mock-model"
    assert isinstance(data["created"], int)
    assert data["id"].startswith("chatcmpl-mock-")

    # Verify choices
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["role"] == "assistant"
    assert isinstance(choice["message"]["content"], str)
    assert len(choice["message"]["content"]) > 0

    # Verify usage
    usage = data["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["is_mock_estimate"] is True

    # Verify response header
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"].startswith("req_")


def test_custom_request_id_preserved(client: TestClient):
    """Verify that a valid client-supplied X-Request-ID header is preserved."""
    custom_rid = "custom-test-id-12345"
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"X-Request-ID": custom_rid},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_rid


def test_invalid_custom_request_id_replaced_with_safe_id(client: TestClient):
    """Verify that unsafe request IDs (e.g. containing illegal characters or too long) are replaced."""
    unsafe_rid = "invalid; injection \n \r"
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    response = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"X-Request-ID": unsafe_rid},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Request-ID"] != unsafe_rid
