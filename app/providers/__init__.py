"""Provider module: base interfaces, implementations, and registry."""

from typing import Dict, Optional
from app.config import Settings, get_settings
from app.providers.base import BaseLLMProvider
from app.providers.failover import (
    FailoverAttempt,
    FailoverExecutionResult,
    StreamingFailoverInitResult,
    classify_failure,
    execute_with_failover,
    init_stream_with_failover,
    validate_fallback_model,
)
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
    elif settings is not None:
        _ollama_provider.base_url = cfg.ollama_base_url.rstrip("/")
        _ollama_provider.timeout = cfg.provider_timeout_seconds
    return _ollama_provider


def get_provider_for_model(
    model: str, settings: Optional[Settings] = None
) -> BaseLLMProvider:
    """Resolve and return provider implementation for a given model identifier.
    
    Routing precedence:
    1. Reject models requiring external providers without an implemented adapter
       (e.g. claude-*, gemini-*, openai)
    2. Vendor prefix routing:
       - 'mock-*' -> MockProvider
    3. Active provider routing:
       - 'ollama' -> OllamaProvider
       - 'mock' -> MockProvider
    4. Default fallback -> MockProvider
    """
    cfg = settings or get_settings()

    # 1. Reject models requiring external providers without an implemented adapter
    from app.pricing.calculator import pricing_engine
    model_meta = pricing_engine.models.get(model)
    if model_meta and model_meta.get("provider") in ("openai", "claude", "gemini"):
        from app.core.errors import InvalidModelError
        raise InvalidModelError(
            f"No provider adapter implemented for model '{model}' (provider: {model_meta.get('provider')})."
        )

    if model.startswith("claude-") or model.startswith("gemini-"):
        from app.core.errors import InvalidModelError
        raise InvalidModelError(f"No provider adapter implemented for model '{model}'.")

    # 2. Vendor prefix routing for mock models
    if model.startswith("mock-"):
        return get_mock_provider()

    # 3. Active provider routing
    if cfg.active_provider == "ollama":
        return get_ollama_provider(cfg)

    # 4. Default fallback for mock mode or unrouted models
    return get_mock_provider()


def get_all_providers(settings: Optional[Settings] = None) -> Dict[str, BaseLLMProvider]:
    """Return dictionary of active providers for health/readiness checks."""
    cfg = settings or get_settings()
    providers: Dict[str, BaseLLMProvider] = {"mock": get_mock_provider()}

    if cfg.active_provider == "ollama":
        providers["ollama"] = get_ollama_provider(cfg)

    return providers


def reset_providers() -> None:
    """Reset provider singletons (useful in testing)."""
    global _ollama_provider
    _ollama_provider = None


async def shutdown_providers() -> None:
    """Clean up open connection pools on application shutdown."""
    global _ollama_provider
    if _ollama_provider is not None:
        await _ollama_provider.aclose()
        _ollama_provider = None
