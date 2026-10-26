"""Phase 9.3.1 Provider Capability Audit Regression Tests.

Validates:
1. Every allowed model has an explicit capability record or documented fallback behavior.
2. Evidence levels clearly distinguish mocked test doubles from live documentation.
3. Unsupported tool-calling requests are rejected with HTTP 400 (unsupported_parameter).
4. Unsupported streaming requests are rejected with HTTP 400 (unsupported_parameter).
5. Tool-calling and streaming combinations are checked independently.
6. Failover skips incompatible models for text, streaming, and tool combinations.
7. JSON Schema limitations are documented for Claude and Gemini.
"""

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.providers.base import (
    get_model_capabilities,
    model_supports_streaming,
    model_supports_streaming_tools,
    model_supports_tools,
)
from app.providers.capabilities import MODEL_CAPABILITIES
from app.providers.failover import validate_fallback_model


def test_every_allowed_model_has_explicit_capability_record():
    """Requirement 1: Every model in allowed_models has an explicit capability record."""
    settings = Settings()
    for model_id in settings.allowed_models:
        cap = get_model_capabilities(model_id)
        assert cap is not None, f"Allowed model '{model_id}' lacks an explicit capability record in MODEL_CAPABILITIES."
        assert cap.model_id == model_id
        assert cap.provider in ("mock", "ollama")
        assert cap.status in ("active", "retired", "restricted_legacy", "test")
        assert cap.evidence_level in (
            "verified_documentation",
            "verified_mocked_test",
            "inferred_family",
            "uncertain",
        )


def test_evidence_classification_distinguishes_mock_from_live():
    """Requirement 2: Mocked tests are clearly distinguished from live-provider verification."""
    # Mock models must be classified as verified_mocked_test
    for mid, cap in MODEL_CAPABILITIES.items():
        if cap.provider == "mock":
            assert cap.evidence_level == "verified_mocked_test", (
                f"Mock model '{mid}' must be classified as 'verified_mocked_test', got '{cap.evidence_level}'"
            )
        elif cap.provider in ("claude", "gemini"):
            assert cap.evidence_level == "verified_documentation", (
                f"Cloud model '{mid}' must be classified as 'verified_documentation', got '{cap.evidence_level}'"
            )


def test_unsupported_tool_calling_rejected(client: TestClient):
    """Requirement 3: Unsupported tool-calling requests are rejected with clean 400 error."""
    # phi3 does not support tools
    payload = {
        "model": "phi3",
        "messages": [{"role": "user", "content": "What is the weather?"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {"loc": {"type": "string"}}},
                },
            }
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "unsupported_parameter"
    assert "does not support tools/function calling" in data["error"]["message"]


def test_unsupported_streaming_rejected(app, client: TestClient, test_settings: Settings):
    """Requirement 4: Unsupported streaming requests are rejected with clean 400 error."""
    custom_settings = test_settings.model_copy(
        update={"allowed_models": test_settings.allowed_models + ["mock-no-streaming"]}
    )
    app.dependency_overrides[get_settings] = lambda: custom_settings

    try:
        payload = {
            "model": "mock-no-streaming",
            "messages": [{"role": "user", "content": "Hello streaming"}],
            "stream": True,
        }
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert data["error"]["code"] == "unsupported_parameter"
        assert "does not support streaming" in data["error"]["message"]
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_tool_calling_and_streaming_checked_independently(app, client: TestClient, test_settings: Settings):
    """Requirement 5: Tool-calling and streaming combinations are checked independently."""
    custom_settings = test_settings.model_copy(
        update={"allowed_models": test_settings.allowed_models + ["mock-no-streaming", "mock-no-tools"]}
    )
    app.dependency_overrides[get_settings] = lambda: custom_settings

    tool_def = [
        {
            "type": "function",
            "function": {
                "name": "calc",
                "description": "Calculator",
                "parameters": {"type": "object", "properties": {"x": {"type": "number"}}},
            },
        }
    ]

    try:
        # Case A: mock-no-streaming with non-streaming text -> 200 OK
        resp_a = client.post(
            "/v1/chat/completions",
            json={"model": "mock-no-streaming", "messages": [{"role": "user", "content": "Hi"}], "stream": False},
        )
        assert resp_a.status_code == 200

        # Case B: mock-no-streaming with non-streaming tools -> 200 OK
        resp_b = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-no-streaming",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
                "tools": tool_def,
            },
        )
        assert resp_b.status_code == 200

        # Case C: mock-no-streaming with stream: true (no tools) -> 400 streaming rejected
        resp_c = client.post(
            "/v1/chat/completions",
            json={"model": "mock-no-streaming", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        )
        assert resp_c.status_code == 400
        assert "does not support streaming" in resp_c.json()["error"]["message"]

        # Case D: mock-no-tools with stream: true (no tools) -> 200 SSE stream OK
        resp_d = client.post(
            "/v1/chat/completions",
            json={"model": "mock-no-tools", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        )
        assert resp_d.status_code == 200
        assert "text/event-stream" in resp_d.headers["content-type"]

        # Case E: mock-no-tools with stream: true and tools -> 400 tool calling rejected
        resp_e = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-no-tools",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
                "tools": tool_def,
            },
        )
        assert resp_e.status_code == 400
        assert "does not support tools/function calling" in resp_e.json()["error"]["message"]

    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_failover_skips_incompatible_models_across_capabilities():
    """Requirement 6: Failover candidate validation respects text, streaming, and tool requirements."""
    settings = Settings(
        allowed_models=["mock-model", "mock-no-streaming", "mock-no-tools", "phi3"],
        failover_allow_mock_fallback=True,
    )

    # 1. Plain text completion: mock-no-streaming and mock-no-tools are valid
    valid, _ = validate_fallback_model(
        "mock-no-streaming", settings, requested_model="mock-model", requires_tools=False, requires_streaming=False
    )
    assert valid is True

    valid, _ = validate_fallback_model(
        "mock-no-tools", settings, requested_model="mock-model", requires_tools=False, requires_streaming=False
    )
    assert valid is True

    # 2. Tool-calling completion (non-streaming): mock-no-tools and phi3 are invalid
    valid_t1, reason_t1 = validate_fallback_model(
        "mock-no-tools", settings, requested_model="mock-model", requires_tools=True, requires_streaming=False
    )
    assert valid_t1 is False
    assert "does not support tool calling" in reason_t1

    valid_t2, reason_t2 = validate_fallback_model(
        "phi3", settings, requested_model="mock-model", requires_tools=True, requires_streaming=False
    )
    assert valid_t2 is False
    assert "does not support tool calling" in reason_t2

    valid_t3, _ = validate_fallback_model(
        "mock-no-streaming", settings, requested_model="mock-model", requires_tools=True, requires_streaming=False
    )
    assert valid_t3 is True

    # 3. Streaming completion (no tools): mock-no-streaming is invalid, mock-no-tools is valid
    valid_s1, reason_s1 = validate_fallback_model(
        "mock-no-streaming", settings, requested_model="mock-model", requires_tools=False, requires_streaming=True
    )
    assert valid_s1 is False
    assert "does not support streaming" in reason_s1

    valid_s2, _ = validate_fallback_model(
        "mock-no-tools", settings, requested_model="mock-model", requires_tools=False, requires_streaming=True
    )
    assert valid_s2 is True

    # 4. Streaming tool calling: requires both streaming and tools
    valid_st1, reason_st1 = validate_fallback_model(
        "mock-no-streaming", settings, requested_model="mock-model", requires_tools=True, requires_streaming=True
    )
    assert valid_st1 is False
    assert ("does not support streaming" in reason_st1 or "streaming tool calling" in reason_st1)

    valid_st2, reason_st2 = validate_fallback_model(
        "mock-no-tools", settings, requested_model="mock-model", requires_tools=True, requires_streaming=True
    )
    assert valid_st2 is False
    assert ("does not support tool calling" in reason_st2 or "streaming tool calling" in reason_st2)

    valid_st3, _ = validate_fallback_model(
        "mock-model", settings, requested_model="mock-model", requires_tools=True, requires_streaming=True
    )
    assert valid_st3 is True


def test_json_schema_limitations_documented():
    """Requirement 7: Provider-specific schema limitations or statuses are recorded."""
    mistral_cap = get_model_capabilities("mistral")
    assert mistral_cap is not None
    assert "Mistral" in mistral_cap.json_schema_limitations

    claude_cap = get_model_capabilities("claude-sonnet-4-6")
    assert claude_cap is not None
    assert "Anthropic adapter removed" in claude_cap.json_schema_limitations

    gemini_cap = get_model_capabilities("gemini-3.8-flash")
    assert gemini_cap is not None
    assert "Gemini adapter removed" in gemini_cap.json_schema_limitations
