"""Tests verifying provider-selection precedence, routing rules, and missing credentials handling."""

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.core.errors import InvalidModelError
from app.main import create_app
from app.providers import (
    get_mock_provider,
    get_ollama_provider,
    get_provider_for_model,
    reset_providers,
)
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


@pytest.fixture(autouse=True)
def clean_singletons():
    reset_providers()
    yield
    reset_providers()


def test_mock_prefix_always_routes_to_mock_provider():
    """Verify models starting with 'mock-' always resolve to MockProvider regardless of active_provider."""
    for prov in ("mock", "ollama"):
        settings = Settings(active_provider=prov)
        resolved = get_provider_for_model("mock-model", settings)
        assert isinstance(resolved, MockProvider)
        assert resolved.name == "mock"


def test_unimplemented_cloud_providers_rejected_with_invalid_model_error():
    """Verify models requiring removed cloud providers (Claude, Gemini) raise clear InvalidModelError."""
    settings = Settings(active_provider="mock")
    for model_name in ("claude-sonnet-4-6", "claude-haiku-4-5-20251001", "gemini-3.8-flash", "gemini-3.5-flash-lite"):
        with pytest.raises(InvalidModelError, match="No provider adapter implemented"):
            get_provider_for_model(model_name, settings)


def test_ollama_models_route_to_ollama_provider_when_active():
    """Verify local models route to OllamaProvider when active_provider is 'ollama' and MockProvider when active_provider is 'mock'."""
    for model_name in ("llama3.2:1b", "phi3:mini", "mistral-7b"):
        settings_ollama = Settings(active_provider="ollama")
        resolved = get_provider_for_model(model_name, settings_ollama)
        assert isinstance(resolved, OllamaProvider)
        assert resolved.name == "ollama"

        settings_mock = Settings(active_provider="mock")
        resolved_mock = get_provider_for_model(model_name, settings_mock)
        assert isinstance(resolved_mock, MockProvider)
        assert resolved_mock.name == "mock"


def test_unprefixed_custom_model_routes_to_active_provider():
    """Verify custom models without a vendor prefix fall back to active_provider."""
    settings_ollama = Settings(active_provider="ollama")
    assert isinstance(get_provider_for_model("custom-support-bot", settings_ollama), OllamaProvider)

    settings_mock = Settings(active_provider="mock")
    assert isinstance(get_provider_for_model("custom-support-bot", settings_mock), MockProvider)


def test_unsupported_model_fails_with_validation_error(tmp_path: Path):
    """Verify requesting a model not in ALLOWED_MODELS produces 400 InvalidModelError."""
    auth_secret = "test_routing_secret_32_chars_minimum"
    client_key = "gw_test_routing_client_key_123456"
    client_verifier = compute_key_verifier(client_key, auth_secret)

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=auth_secret,
        client_keys=[{"client_id": "test_client", "verifier": client_verifier, "enabled": True}],
        database_url=f"sqlite:///{tmp_path / 'routing_test3.db'}",
        allowed_models=["mock-model"],
        active_provider="mock",
        cache_enabled=False,
        guardrails_enabled=False,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app, headers={"Authorization": f"Bearer {client_key}"}) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "unsupported-model-not-allowed",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "invalid_model"
    assert "is not permitted or supported" in data["error"]["message"]


def test_retired_models_not_in_default_allowed_models_fail_safely(tmp_path: Path):
    """Verify default Settings excludes retired/restricted models and rejects them with 400 InvalidModelError."""
    auth_secret = "test_routing_secret_32_chars_minimum"
    client_key = "gw_test_routing_client_key_123456"
    client_verifier = compute_key_verifier(client_key, auth_secret)

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=auth_secret,
        client_keys=[{"client_id": "test_client", "verifier": client_verifier, "enabled": True}],
        database_url=f"sqlite:///{tmp_path / 'routing_retired.db'}",
        cache_enabled=False,
        guardrails_enabled=False,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    retired_or_restricted_models = [
        "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    with TestClient(app, headers={"Authorization": f"Bearer {client_key}"}) as client:
        for model in retired_or_restricted_models:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert resp.status_code == 400
            data = resp.json()
            assert data["error"]["code"] == "invalid_model"
            assert "is not permitted or supported" in data["error"]["message"]


def test_default_allowed_models_route_cleanly_to_adapters():
    """Verify all active default models are permitted and route to their respective provider."""
    settings = Settings()

    # Local Ollama models
    settings_ollama = Settings(active_provider="ollama")
    for m in ("llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M", "llama3.2", "phi3", "mistral"):
        prov = get_provider_for_model(m, settings_ollama)
        assert isinstance(prov, OllamaProvider)
        assert prov.name == "ollama"

    # Mock models
    for m in ("mock-model", "mock-timeout", "mock-error"):
        prov_mock = get_provider_for_model(m, settings)
        assert isinstance(prov_mock, MockProvider)
        assert prov_mock.name == "mock"
