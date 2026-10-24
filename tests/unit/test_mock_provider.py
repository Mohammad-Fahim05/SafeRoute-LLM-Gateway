"""Unit tests for MockProvider behavior and network isolation."""

import socket
from unittest.mock import patch
import pytest

from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.core.errors import ProviderError, ProviderMalformedResponseError
from app.providers.mock import MockProvider


def test_mock_provider_deterministic_response():
    """Verify mock provider returns expected predictable response and token estimates."""
    async def _test():
        provider = MockProvider()
        request = ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Hello test!")],
        )

        response = await provider.complete(request)
        assert response.object == "chat.completion"
        assert response.model == "mock-model"
        assert len(response.choices) == 1
        assert response.choices[0].message.role == "assistant"
        assert "SafeRoute mock provider" in response.choices[0].message.content
        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0
        assert response.usage.total_tokens == response.usage.prompt_tokens + response.usage.completion_tokens
        assert response.usage.is_mock_estimate is True

    import asyncio
    asyncio.run(_test())


def test_mock_provider_error_simulation():
    """Verify mock provider raises ProviderError for mock-error model."""
    async def _test():
        provider = MockProvider()
        request = ChatCompletionRequest(
            model="mock-error",
            messages=[ChatMessage(role="user", content="Trigger error")],
        )

        with pytest.raises(ProviderError):
            await provider.complete(request)

    import asyncio
    asyncio.run(_test())


def test_mock_provider_malformed_simulation():
    """Verify mock provider raises ProviderMalformedResponseError for mock-malformed model."""
    async def _test():
        provider = MockProvider()
        request = ChatCompletionRequest(
            model="mock-malformed",
            messages=[ChatMessage(role="user", content="Trigger malformed")],
        )

        with pytest.raises(ProviderMalformedResponseError):
            await provider.complete(request)

    import asyncio
    asyncio.run(_test())


def test_mock_provider_makes_no_network_calls():
    """Verify mock provider operates strictly in-memory without initiating network sockets."""
    async def _test():
        provider = MockProvider()
        request = ChatCompletionRequest(
            model="mock-model",
            messages=[ChatMessage(role="user", content="Verify offline execution")],
        )

        with patch.object(socket, "socket", side_effect=RuntimeError("Network access forbidden")):
            response = await provider.complete(request)
            assert response is not None
            assert response.model == "mock-model"

    import asyncio
    asyncio.run(_test())


def test_mock_provider_health_check():
    """Verify mock provider readiness probe returns True."""
    async def _test():
        provider = MockProvider()
        assert await provider.check_health() is True

    import asyncio
    asyncio.run(_test())
