"""Provider module: base interfaces, implementations, and registry."""

from typing import Dict
from app.providers.base import BaseLLMProvider
from app.providers.mock import MockProvider

_PROVIDER_REGISTRY: Dict[str, BaseLLMProvider] = {
    "mock": MockProvider(),
}


def get_provider_for_model(model: str) -> BaseLLMProvider:
    """Resolve and return provider implementation for a given model identifier.
    
    In Phase 1, all allowed mock models are routed to the MockProvider.
    Future phases can register OllamaProvider, ClaudeProvider, or OpenAIProvider here.
    """
    # Phase 1: All supported models are mock models
    return _PROVIDER_REGISTRY["mock"]


def get_all_providers() -> Dict[str, BaseLLMProvider]:
    """Return dictionary of all active providers."""
    return _PROVIDER_REGISTRY.copy()
