"""Provider module: base interfaces, implementations, and registry."""

from typing import Dict, Optional
from app.config import Settings, get_settings
from app.providers.base import BaseLLMProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider

_mock_provider = MockProvider()
_ollama_provider: Optional[OllamaProvider] = None


def get_mock_provider() -> MockProvider:
    """Return singleton instance of MockProvider."""
    return _mock_provider


def get_ollama_provider(settings: Optional[Settings] = None) -> OllamaProvider:
    """Return or initialize OllamaProvider with configured settings."""
    global _ollama_provider
    cfg = settings or get_settings()
    if _ollama_provider is None:
        _ollama_provider = OllamaProvider(
            base_url=cfg.ollama_base_url,
            timeout=cfg.provider_timeout_seconds,
        )
    return _ollama_provider


def get_provider_for_model(
    model: str, settings: Optional[Settings] = None
) -> BaseLLMProvider:
    """Resolve and return provider implementation for a given model identifier.
    
    Routes models based on configured active_provider:
    - If active_provider is 'mock' or model is a mock-* model -> MockProvider
    - If active_provider is 'ollama' -> OllamaProvider
    """
    cfg = settings or get_settings()

    # Explicit mock models always route to mock provider for testing
    if model.startswith("mock-") or cfg.active_provider == "mock":
        return get_mock_provider()

    if cfg.active_provider == "ollama":
        return get_ollama_provider(cfg)

    # Fallback to mock provider
    return get_mock_provider()


def get_all_providers(settings: Optional[Settings] = None) -> Dict[str, BaseLLMProvider]:
    """Return dictionary of active providers for health/readiness checks."""
    cfg = settings or get_settings()
    providers: Dict[str, BaseLLMProvider] = {"mock": get_mock_provider()}

    if cfg.active_provider == "ollama":
        providers["ollama"] = get_ollama_provider(cfg)

    return providers


async def shutdown_providers() -> None:
    """Clean up open connection pools on application shutdown."""
    global _ollama_provider
    if _ollama_provider is not None:
        await _ollama_provider.aclose()
        _ollama_provider = None
