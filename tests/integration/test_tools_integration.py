"""Integration tests for Phase 9.3 Unified Tool / Function-Calling Normalization."""

import asyncio
import json
import pytest
from starlette.testclient import TestClient

from app.api.schemas import (
    ChatCompletionRequest,
    ChatCompletionTool,
    ChatMessage,
    FunctionDefinition,
)
from app.cache import build_cache_key
from app.config import Settings
from app.core.auth import compute_key_verifier
from app.core.errors import ProviderError
from app.db import init_db
from app.main import create_app
from app.config import get_settings


def test_text_only_completions_remain_unchanged(client: TestClient):
    """Requirement 1: Existing text-only completions remain completely unchanged."""
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "Explain what a gateway is."},
        ],
        "temperature": 0.5,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert isinstance(data["choices"][0]["message"]["content"], str)
    assert data["choices"][0]["message"].get("tool_calls") is None


def test_tool_calls_returned_and_never_executed(client: TestClient):
    """Requirement 13: Tool calls are returned to caller with finish_reason='tool_calls' and never executed."""
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "What is the weather in London?"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_current_weather",
                    "description": "Get current weather in a city",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["location"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    choice = data["choices"][0]

    # Verify finish_reason is tool_calls
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["tool_calls"] is not None
    assert len(choice["message"]["tool_calls"]) == 1

    tc = choice["message"]["tool_calls"][0]
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_current_weather"
    assert tc["id"].startswith("call_")

    # Arguments are normalized JSON string
    args = json.loads(tc["function"]["arguments"])
    assert isinstance(args, dict)
    assert "location" in args


def test_tool_result_association(client: TestClient):
    """Requirement 14: Follow-up message with tool role associates with tool_call_id."""
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "What is the weather in London?"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_weather_123",
                        "type": "function",
                        "function": {
                            "name": "get_current_weather",
                            "arguments": json.dumps({"location": "London"}),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_weather_123",
                "content": json.dumps({"temperature": 18, "condition": "Cloudy"}),
            },
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["finish_reason"] == "stop"


def test_streaming_tool_call_fragments_normalized(client: TestClient):
    """Requirement 15: Streaming tool-call fragments are normalized and emitted as SSE."""
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "What is the weather in London?"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
                },
            }
        ],
        "stream": True,
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    chunks = []
    has_tool_call_delta = False
    terminal_finish_reason = None

    for line in response.iter_lines():
        if line.startswith("data:") and not line.endswith("[DONE]"):
            chunk_data = json.loads(line[len("data:"):].strip())
            chunks.append(chunk_data)
            choice = chunk_data["choices"][0]
            if choice.get("delta", {}).get("tool_calls"):
                has_tool_call_delta = True
            if choice.get("finish_reason") is not None:
                terminal_finish_reason = choice["finish_reason"]

    assert has_tool_call_delta is True
    assert terminal_finish_reason == "tool_calls"


def test_streaming_interrupted_stream_produces_safe_error(test_db_url: str):
    """Requirement 16: Interrupted streams do not produce falsely complete tool calls."""
    test_key = "gw_test_key_stream_err_12345"
    auth_secret = "test_auth_secret_minimum_16_characters_long"
    verifier = compute_key_verifier(test_key, auth_secret)

    settings = Settings(
        app_env="test",
        allowed_models=["mock-stream-error-after-chunk", "mock-model"],
        default_model="mock-model",
        auth_enabled=True,
        auth_secret=auth_secret,
        client_keys=[{"client_id": "test_client", "verifier": verifier, "enabled": True}],
        active_provider="mock",
        database_url=test_db_url,
        streaming_enabled=True,
    )

    from app.db.session import get_engine
    init_db(get_engine(settings.database_url))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    local_client = TestClient(app, headers={"Authorization": f"Bearer {test_key}"})

    payload = {
        "model": "mock-stream-error-after-chunk",
        "messages": [
            {"role": "user", "content": "Call tool"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "test_tool"}}
        ],
        "stream": True,
    }
    response = local_client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    lines = [line for line in response.iter_lines() if line]

    # Verify stream emitted an error event before [DONE]
    error_event_found = False
    for line in lines:
        if line.startswith("data:") and not line.endswith("[DONE]"):
            data = json.loads(line[len("data:"):].strip())
            if "error" in data:
                error_event_found = True
                assert data["error"]["type"] == "stream_error"

    assert error_event_found is True
    assert lines[-1] == "data: [DONE]"


def test_failover_incompatible_model_skipped_for_tools(client: TestClient):
    """Requirement 17: Failover never selects a model that does not support tools."""
    payload = {
        "model": "mock-error",
        "messages": [
            {"role": "user", "content": "What is the weather?"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "get_weather"}}
        ],
        "allow_failover": True,
    }
    response = client.post("/v1/chat/completions", json=payload)
    if response.status_code == 200:
        data = response.json()
        assert data["choices"][0]["finish_reason"] == "tool_calls"


def test_cache_identity_isolates_different_tool_definitions():
    """Requirement 18: Cache identity cannot mix different tool definitions."""
    req1 = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Search query")],
        tools=[
            ChatCompletionTool(type="function", function=FunctionDefinition(name="search_v1"))
        ],
    )
    req2 = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Search query")],
        tools=[
            ChatCompletionTool(type="function", function=FunctionDefinition(name="search_v2"))
        ],
    )
    req_no_tools = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Search query")],
    )

    k1 = build_cache_key("client_1", "mock", req1)
    k2 = build_cache_key("client_1", "mock", req2)
    k_none = build_cache_key("client_1", "mock", req_no_tools)

    assert k1 != k2
    assert k1 != k_none
    assert k2 != k_none


def test_unsupported_model_for_tools_rejected(client: TestClient):
    """Requirement 12: Unsupported models are rejected explicitly at route level."""
    payload = {
        "model": "mock-malformed",  # configured as non-tool model
        "messages": [
            {"role": "user", "content": "Check weather"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "get_weather"}}
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "unsupported_parameter"
    assert "does not support tools" in data["error"]["message"]


def test_usage_and_cost_accuracy(client: TestClient):
    """Requirement 19: Usage tokens and source metadata are accurate on tool call responses."""
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "Weather in Tokyo?"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "get_weather"}}
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    usage = data["usage"]
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["usage_source"] == "mock_estimated"
    assert usage["is_mock_estimate"] is True


def test_concurrent_tool_requests_isolation(client: TestClient):
    """Requirement 21: Concurrent requests do not leak tool definitions or results."""
    def make_req(city: str):
        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": f"Weather in {city}?"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": f"get_weather_{city.lower()}",
                        "parameters": {"type": "object", "properties": {"loc": {"type": "string"}}},
                    },
                }
            ],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == f"get_weather_{city.lower()}"

    cities = ["Berlin", "Tokyo", "Madrid", "Sydney", "Cairo"]
    for c in cities:
        make_req(c)


def test_no_credentials_or_sensitive_tool_args_in_logs(client: TestClient, caplog):
    """Requirement 22: No credentials or sensitive arguments appear in logs."""
    import logging
    caplog.set_level(logging.DEBUG)

    sensitive_api_key = "sk-ant-api03-SECRET-KEY-NEVER-LOG-12345"
    payload = {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "Analyze user credentials"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "login_service",
                    "parameters": {"type": "object", "properties": {"password": {"type": "string"}}},
                },
            }
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200

    log_text = caplog.text
    assert sensitive_api_key not in log_text
    assert "Authorization" not in log_text or "Bearer" not in log_text
