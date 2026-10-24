"""Base provider interface for LLM backends."""

from abc import ABC, abstractmethod

from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse


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
    async def check_health(self) -> bool:
        """Verify provider availability for readiness checks."""
        pass
