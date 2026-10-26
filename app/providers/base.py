"""Base provider interface for LLM backends."""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.api.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)


from app.providers.capabilities import (
    ModelCapability,
    get_model_capabilities,
    model_supports_streaming,
    model_supports_streaming_tools,
    model_supports_tools,
)


class BaseLLMProvider(ABC):
    """Abstract base class that all provider implementations (Mock, Ollama, Claude, etc.) must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier name."""
        pass

    @abstractmethod
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Submit a validated chat completion request and return a normalized response."""
        pass

    @abstractmethod
    async def stream_complete(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Submit a validated chat completion request and yield normalized streaming chunks."""
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """Verify provider availability for readiness checks."""
        pass

    def supports_tools(self, model: str) -> bool:
        """Check whether this provider supports tool/function calling for the specified model."""
        return model_supports_tools(model)

    def supports_streaming(self, model: str) -> bool:
        """Check whether this provider supports streaming completions for the specified model."""
        return model_supports_streaming(model)


__all__ = [
    "BaseLLMProvider",
    "ModelCapability",
    "get_model_capabilities",
    "model_supports_tools",
    "model_supports_streaming",
    "model_supports_streaming_tools",
]
