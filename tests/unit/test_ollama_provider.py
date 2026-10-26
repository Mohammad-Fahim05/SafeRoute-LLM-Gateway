"""Unit tests for OllamaProvider using httpx.MockTransport."""

import asyncio
import json
import httpx
import pytest

from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.core.errors import (
    InvalidModelError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderTimeoutError,
)
from app.providers.ollama import OllamaProvider


def test_ollama_successful_response_mapping():
    """Requirement 9 & 10: Verify successful response maps correctly and extracts token counts."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/chat"
            body = json.loads(request.content)
            assert body["model"] == "llama3.2:1b"
            assert len(body["messages"]) == 1
            assert body["options"]["temperature"] == 0.5
            assert body["options"]["num_predict"] == 150

            mock_response = {
                "model": "llama3.2:1b",
                "created_at": "2026-10-24T18:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "Ollama is running locally.",
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 18,
                "eval_count": 25,
            }
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello Ollama")],
            temperature=0.5,
            max_completion_tokens=150,
        )

        res = await provider.complete(req)
        assert res.model == "llama3.2:1b"
        assert res.object == "chat.completion"
        assert len(res.choices) == 1
        assert res.choices[0].message.role == "assistant"
        assert res.choices[0].message.content == "Ollama is running locally."
        assert res.choices[0].finish_reason == "stop"
        assert res.usage.prompt_tokens == 18
        assert res.usage.completion_tokens == 25
        assert res.usage.total_tokens == 43
        assert res.usage.is_mock_estimate is False
        assert res.usage.usage_source == "provider_reported"

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_missing_usage_handled_as_unavailable():
    """Requirement 11: Verify missing usage counts are represented as None/unavailable and not labeled as mock."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            mock_response = {
                "model": "llama3.2:1b",
                "message": {"role": "assistant", "content": "Response without usage counts"},
                "done": True,
            }
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        res = await provider.complete(req)
        assert res.usage.prompt_tokens is None
        assert res.usage.completion_tokens is None
        assert res.usage.total_tokens is None
        assert res.usage.is_mock_estimate is False
        assert res.usage.usage_source == "unavailable"

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_partial_usage_preserves_available_and_none_total():
    """Requirement 11: Verify partial usage preserves known counts, keeps missing as None, and leaves total as None."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            mock_response = {
                "model": "llama3.2:1b",
                "message": {"role": "assistant", "content": "Response with prompt eval only"},
                "done": True,
                "prompt_eval_count": 22,
                # eval_count is omitted / missing
            }
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        res = await provider.complete(req)
        assert res.usage.prompt_tokens == 22
        assert res.usage.completion_tokens is None
        assert res.usage.total_tokens is None
        assert res.usage.is_mock_estimate is False
        assert res.usage.usage_source == "provider_reported"

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_explicit_zero_usage_preserved():
    """Requirement 11: Verify explicit zero token counts are preserved as 0, not confused with None/missing."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            mock_response = {
                "model": "llama3.2:1b",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": 15,
                "eval_count": 0,
            }
            return httpx.Response(200, json=mock_response)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        res = await provider.complete(req)
        assert res.usage.prompt_tokens == 15
        assert res.usage.completion_tokens == 0
        assert res.usage.total_tokens == 15
        assert res.usage.is_mock_estimate is False
        assert res.usage.usage_source == "provider_reported"

        await provider.aclose()

    asyncio.run(_test())



def test_ollama_connection_error():
    """Requirement 12: Connection error raises ProviderError."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused by localhost:11434")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        with pytest.raises(ProviderError, match="unreachable or not running"):
            await provider.complete(req)

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_timeout_error():
    """Requirement 13: Timeout raises ProviderTimeoutError."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client, timeout=2.0)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        with pytest.raises(ProviderTimeoutError, match="timed out"):
            await provider.complete(req)

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_model_not_found():
    """Requirement 14: HTTP 404 from Ollama raises InvalidModelError."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="model 'nonexistent' not found")

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        with pytest.raises(InvalidModelError, match="not found in the local Ollama"):
            await provider.complete(req)

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_malformed_response():
    """Requirement 15: Malformed JSON or missing content raises ProviderMalformedResponseError."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            # Valid JSON but missing message content field
            return httpx.Response(200, json={"model": "llama3.2:1b", "message": {}})

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434")
        provider = OllamaProvider(http_client=client)

        req = ChatCompletionRequest(
            model="llama3.2:1b",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        with pytest.raises(ProviderMalformedResponseError, match="missing message content"):
            await provider.complete(req)

        await provider.aclose()

    asyncio.run(_test())


def test_ollama_client_cleanup():
    """Requirement 16: Verify aclose closes the HTTP client."""
    async def _test():
        provider = OllamaProvider()
        client = await provider.get_client()
        assert not client.is_closed
        await provider.aclose()
        assert client.is_closed

    asyncio.run(_test())


def test_ollama_health_check_probes():
    """Verify check_health returns True on 200 and False on failure."""
    async def _test():
        def success_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"version": "0.34.0"})

        def fail_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal error")

        p_success = OllamaProvider(
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(success_handler),
                base_url="http://localhost:11434",
            )
        )
        p_fail = OllamaProvider(
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(fail_handler),
                base_url="http://localhost:11434",
            )
        )

        assert await p_success.check_health() is True
        assert await p_fail.check_health() is False

        await p_success.aclose()
        await p_fail.aclose()

    asyncio.run(_test())


def test_ollama_constructor_settings_support():
    """Verify OllamaProvider constructor accepts settings object and configures base_url and timeout."""
    from app.config import Settings
    custom_settings = Settings(
        ollama_base_url="http://custom-ollama:11434",
        provider_timeout_seconds=12.5,
    )
    p = OllamaProvider(settings=custom_settings)
    assert p.base_url == "http://custom-ollama:11434"
    assert p.timeout == 12.5


def test_ollama_qwen25_coder_mock_completion():
    """Verify qwen2.5-coder:7b-instruct-q4_K_M model completes cleanly with canonical response."""
    async def _test():
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/chat"
            body = json.loads(request.content)
            assert body["model"] == "qwen2.5-coder:7b-instruct-q4_K_M"

            mock_response = {
                "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                "created_at": "2026-10-25T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "def hello_world(): return 'hello'",
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 20,
                "eval_count": 10,
            }
            return httpx.Response(200, json=mock_response)

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://localhost:11434",
        )
        provider = OllamaProvider(http_client=client)
        req = ChatCompletionRequest(
            model="qwen2.5-coder:7b-instruct-q4_K_M",
            messages=[ChatMessage(role="user", content="Write a hello world function")],
        )
        res = await provider.complete(req)
        assert res.model == "qwen2.5-coder:7b-instruct-q4_K_M"
        assert res.choices[0].message.content == "def hello_world(): return 'hello'"
        assert res.usage.prompt_tokens == 20
        assert res.usage.completion_tokens == 10
        assert res.usage.total_tokens == 30

        await provider.aclose()

    asyncio.run(_test())
