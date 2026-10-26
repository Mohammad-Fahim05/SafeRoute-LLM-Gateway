"""Unit tests for SafeRoute Phase 11C Streaming Cache Replay."""

import asyncio
import json
import pytest

from app.api.schemas import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionChunk,
    ChatCompletionMessageToolCall,
    ChatCompletionRequest,
    ChatCompletionResponse,
    FunctionCall,
    UsageInfo,
)
from app.api.routes import _sse_replay_generator
from app.cache import build_cache_key
from app.config import Settings
from app.metrics import get_metrics
from tests.unit.test_cache import FakeAsyncRedis


def parse_sse_events(lines_list):
    """Parse list of SSE lines into event objects or string literals."""
    events = []
    for chunk in lines_list:
        for line in chunk.split("\n"):
            stripped = line.strip()
            if stripped.startswith("data:"):
                payload = stripped[len("data:"):].strip()
                if payload == "[DONE]":
                    events.append("[DONE]")
                else:
                    try:
                        events.append(json.loads(payload))
                    except Exception:
                        events.append(payload)
    return events


@pytest.mark.anyio
async def test_streaming_cache_replay_generator_emits_valid_openai_chunks():
    """Verify _sse_replay_generator yields valid OpenAI-compatible chunks and terminal done."""
    cached_resp = ChatCompletionResponse(
        id="chatcmpl-cached-123",
        created=1700000000,
        model="mock-model",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(
                    role="assistant",
                    content="Hello world, this is a cached response.",
                ),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(
            prompt_tokens=5,
            completion_tokens=8,
            total_tokens=13,
            usage_source="provider_reported",
            is_mock_estimate=False,
        ),
    )

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    settings = Settings(app_env="test", metrics_enabled=True)

    chunks = []
    async for sse_line in _sse_replay_generator(
        cached_resp=cached_resp,
        request_id="req_test_123",
        client_id="alice",
        request=req,
        provider_name="mock",
        route_start=0.0,
        settings=settings,
        cache_layer="exact",
    ):
        chunks.append(sse_line)

    events = parse_sse_events(chunks)
    assert len(events) >= 3  # role chunk + at least 1 content chunk + finish chunk + [DONE]
    assert events[-1] == "[DONE]"

    # First event must be the role announcement
    role_ev = events[0]
    assert role_ev["object"] == "chat.completion.chunk"
    assert role_ev["id"] == "chatcmpl-req_test_123"
    assert role_ev["choices"][0]["delta"]["role"] == "assistant"
    assert role_ev["choices"][0].get("finish_reason") is None

    # Middle events must carry content deltas
    content_pieces = [
        ev["choices"][0]["delta"]["content"]
        for ev in events[:-2]
        if isinstance(ev, dict) and "content" in ev.get("choices", [{}])[0].get("delta", {})
    ]
    reconstructed = "".join(content_pieces)
    assert reconstructed == "Hello world, this is a cached response."

    # Penultimate event must carry terminal finish_reason and usage
    finish_ev = events[-2]
    assert finish_ev["choices"][0]["finish_reason"] == "stop"
    assert finish_ev["usage"]["prompt_tokens"] == 5
    assert finish_ev["usage"]["completion_tokens"] == 8


@pytest.mark.anyio
async def test_streaming_cache_replay_generator_emits_tool_calls():
    """Verify tool calls in cached response are properly replayed with tool_calls deltas."""
    cached_resp = ChatCompletionResponse(
        id="chatcmpl-cached-tc",
        created=1700000000,
        model="mock-model",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id="call_mock_1",
                            type="function",
                            function=FunctionCall(
                                name="get_weather",
                                arguments='{"city": "Paris"}',
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=UsageInfo(
            prompt_tokens=10,
            completion_tokens=15,
            total_tokens=25,
            usage_source="provider_reported",
            is_mock_estimate=False,
        ),
    )

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Weather in Paris"}],
        stream=True,
    )
    settings = Settings(app_env="test", metrics_enabled=True)

    chunks = []
    async for sse_line in _sse_replay_generator(
        cached_resp=cached_resp,
        request_id="req_tc_123",
        client_id="alice",
        request=req,
        provider_name="mock",
        route_start=0.0,
        settings=settings,
        cache_layer="exact",
    ):
        chunks.append(sse_line)

    events = parse_sse_events(chunks)
    assert events[-1] == "[DONE]"

    # Find the tool call chunk
    tc_events = [
        ev for ev in events if isinstance(ev, dict)
        and ev.get("choices", [{}])[0].get("delta", {}).get("tool_calls")
    ]
    assert len(tc_events) == 1
    tc_delta = tc_events[0]["choices"][0]["delta"]["tool_calls"][0]
    assert tc_delta["id"] == "call_mock_1"
    assert tc_delta["function"]["name"] == "get_weather"
    assert tc_delta["function"]["arguments"] == '{"city": "Paris"}'

    # Check terminal finish reason
    finish_ev = events[-2]
    assert finish_ev["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.anyio
async def test_streaming_cache_replay_generator_active_streams_gauge():
    """Verify active streaming requests gauge increments on replay start and decrements on finish."""
    metrics = get_metrics()
    before_gauge = metrics.streaming_requests_active._value.get()

    cached_resp = ChatCompletionResponse(
        id="chatcmpl-cached-gauge",
        created=1700000000,
        model="mock-model",
        choices=[
            ChatChoice(
                index=0,
                message=ChatChoiceMessage(role="assistant", content="Test"),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(
            prompt_tokens=2,
            completion_tokens=2,
            total_tokens=4,
            usage_source="provider_reported",
            is_mock_estimate=False,
        ),
    )

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    settings = Settings(app_env="test", metrics_enabled=True)

    gen = _sse_replay_generator(
        cached_resp=cached_resp,
        request_id="req_gauge_1",
        client_id="alice",
        request=req,
        provider_name="mock",
        route_start=0.0,
        settings=settings,
        cache_layer="exact",
    )

    # Prime generator
    await gen.__anext__()
    during_gauge = metrics.streaming_requests_active._value.get()
    assert during_gauge == before_gauge + 1

    # Exhaust generator
    try:
        while True:
            await gen.__anext__()
    except StopAsyncIteration:
        pass

    after_gauge = metrics.streaming_requests_active._value.get()
    assert after_gauge == before_gauge


def test_streaming_cache_key_equivalence_for_stream_param():
    """Verify stream=True and stream=False produce identical keys for compatible response reuse."""
    req_stream = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "What is 2+2?"}],
        stream=True,
        temperature=0.7,
        max_completion_tokens=50,
    )
    req_non_stream = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "What is 2+2?"}],
        stream=False,
        temperature=0.7,
        max_completion_tokens=50,
    )

    key_stream = build_cache_key("client_1", "mock", req_stream)
    key_non_stream = build_cache_key("client_1", "mock", req_non_stream)

    assert key_stream == key_non_stream


def test_streaming_cache_key_differentiation():
    """Verify different models, prompts, temperatures, and clients create distinct keys."""
    base_req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
        temperature=0.5,
    )
    diff_temp = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
        temperature=0.9,
    )
    diff_prompt = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Goodbye"}],
        stream=True,
        temperature=0.5,
    )

    k_base = build_cache_key("alice", "mock", base_req)
    k_temp = build_cache_key("alice", "mock", diff_temp)
    k_prompt = build_cache_key("alice", "mock", diff_prompt)
    k_bob = build_cache_key("bob", "mock", base_req)

    assert k_base != k_temp
    assert k_base != k_prompt
    assert k_base != k_bob
    assert "alice" in k_base
    assert "bob" in k_bob
