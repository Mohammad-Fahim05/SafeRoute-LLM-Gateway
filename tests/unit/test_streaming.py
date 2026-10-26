"""Unit tests for streaming provider adapters and failover initialization."""

import asyncio
import json
import time
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock

from app.api.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatMessage,
)
from app.config import Settings
from app.core.errors import (
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from app.providers.failover import (
    StreamingFailoverInitResult,
    init_stream_with_failover,
)
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


@pytest.mark.anyio
async def test_mock_provider_streaming_chunks():
    """Verify MockProvider yields ordered chunks with proper finish reason and usage."""
    provider = MockProvider()
    req = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Hello test")],
        stream=True,
    )
    chunks = []
    async for chunk in provider.stream_complete(req):
        chunks.append(chunk)

    assert len(chunks) > 1
    # Check that contents match words
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text.strip() == "This is a deterministic response from the SafeRoute mock provider."
    # Initial chunk has role "assistant"
    assert chunks[0].choices[0].delta.role == "assistant"
    # Final chunk has finish_reason "stop" and usage
    last_chunk = chunks[-1]
    assert last_chunk.choices[0].finish_reason == "stop"
    assert last_chunk.usage is not None
    assert last_chunk.usage.prompt_tokens == 2
    assert last_chunk.usage.completion_tokens > 0
    assert last_chunk.usage.total_tokens == last_chunk.usage.prompt_tokens + last_chunk.usage.completion_tokens


@pytest.mark.anyio
async def test_mock_provider_streaming_empty_and_short():
    """Verify MockProvider handles empty and short responses cleanly."""
    provider = MockProvider()

    # 1. Empty response
    req_empty = ChatCompletionRequest(
        model="mock-empty-response",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    empty_chunks = [c async for c in provider.stream_complete(req_empty)]
    assert len(empty_chunks) == 1
    assert empty_chunks[0].choices[0].delta.content == ""
    assert empty_chunks[0].choices[0].finish_reason == "stop"

    # 2. Short response (emits content chunk and terminal chunk)
    req_short = ChatCompletionRequest(
        model="mock-short-response",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    short_chunks = [c async for c in provider.stream_complete(req_short)]
    assert len(short_chunks) == 2
    assert short_chunks[0].choices[0].delta.content == "Hello!"
    assert short_chunks[1].choices[0].finish_reason == "stop"


@pytest.mark.anyio
async def test_mock_provider_streaming_errors_and_timeouts():
    """Verify MockProvider error modes raise expected typed exceptions."""
    provider = MockProvider()

    # 1. Timeout simulation: stream sleeps 10s, timing out via wait_for
    req_to = ChatCompletionRequest(
        model="mock-timeout",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    gen = provider.stream_complete(req_to)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await gen.__anext__()

    # 2. Error
    req_err = ChatCompletionRequest(
        model="mock-error",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    with pytest.raises(ProviderError):
        async for _ in provider.stream_complete(req_err):
            pass

    # 3. Rate limit
    req_rl = ChatCompletionRequest(
        model="mock-rate-limit",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    with pytest.raises(ProviderRateLimitError) as exc_info:
        async for _ in provider.stream_complete(req_rl):
            pass
    assert exc_info.value.retry_after == 0.1


@pytest.mark.anyio
async def test_mock_provider_programmatic_midstream_failure():
    """Verify MockProvider programmatic mid-stream failure triggers mid-stream exception."""
    provider = MockProvider()
    provider.set_stream_failure_after_chunks("mock-model", ProviderError("Midstream connection reset"), chunk_count=2)

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )
    received = []
    with pytest.raises(ProviderError) as exc_info:
        async for chunk in provider.stream_complete(req):
            received.append(chunk)

    assert len(received) == 2
    assert "Midstream connection reset" in str(exc_info.value)

    # Reset
    provider.reset_custom_behaviors()




@pytest.mark.anyio
async def test_ollama_provider_streaming_ndjson_parsing():
    """Verify OllamaProvider correctly parses ndjson stream and extracts eval counts."""
    provider = OllamaProvider(base_url="http://localhost:11434")

    ndjson_lines = [
        '{"message": {"role": "assistant", "content": "Hello "}, "done": false}\n',
        '{"message": {"role": "assistant", "content": "Ollama!"}, "done": true, "prompt_eval_count": 8, "eval_count": 4}\n',
    ]

    async def mock_aiter_lines():
        for line in ndjson_lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = mock_aiter_lines
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.stream = MagicMock(return_value=mock_resp)
    provider._client = mock_client

    req = ChatCompletionRequest(
        model="llama3.2:1b",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    chunks = []
    async for chunk in provider.stream_complete(req):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].choices[0].delta.content == "Hello "
    assert chunks[1].choices[0].delta.content == "Ollama!"
    assert chunks[2].choices[0].finish_reason == "stop"
    assert chunks[2].usage is not None
    assert chunks[2].usage.prompt_tokens == 8
    assert chunks[2].usage.completion_tokens == 4
    assert chunks[2].usage.total_tokens == 12
    assert chunks[2].usage.usage_source == "provider_reported"


@pytest.mark.anyio
async def test_init_stream_with_failover_pre_stream_fallback():
    """Verify init_stream_with_failover catches primary failure on chunk #0 and falls over."""
    settings = Settings(
        failover_enabled=True,
        failover_allow_mock_fallback=True,
        failover_fallback_models={"mock-error": ["mock-model"]},
        failover_max_attempts=2,
    )

    req = ChatCompletionRequest(
        model="mock-error",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    def resolver(m: str, s: Settings):
        return MockProvider()

    res = await init_stream_with_failover(
        request=req,
        settings=settings,
        allow_failover=True,
        provider_resolver=resolver,
        overall_start_time=time.perf_counter(),
    )

    assert isinstance(res, StreamingFailoverInitResult)
    assert res.failover_occurred is True
    assert res.serving_model == "mock-model"
    assert len(res.attempts) == 2
    assert res.attempts[0].success is False
    assert res.attempts[1].success is True
    assert res.first_chunk is not None
