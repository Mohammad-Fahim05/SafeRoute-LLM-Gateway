"""Unit and regression tests for Phase 9.3.2 Active Model Catalog Consistency Audit.

Validates:
1. Every selectable model has an implemented provider adapter.
2. Active allowlists exclude retired models; requests for retired models are rejected.
3. Restricted legacy models follow explicit configured access policy.
4. Reference unsupported model (gpt-4o-mini) is rejected for execution while pricing is preserved.
5. Pricing catalog and capability registry entries agree for all selectable models.
6. Failover validation prevents selecting retired, restricted, or unsupported reference models.
7. Historical billing records remain accurately computable across all catalog entries.
8. Unknown and unverified models fail safely.
"""

from decimal import Decimal
import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.core.errors import InvalidModelError
from app.pricing.calculator import PricingEngine
from app.providers import get_provider_for_model
from app.providers.base import (
    get_model_capabilities,
    model_supports_streaming,
    model_supports_streaming_tools,
    model_supports_tools,
)
from app.providers.capabilities import MODEL_CAPABILITIES
from app.providers.failover import validate_fallback_model


def test_every_selectable_model_has_implemented_provider_adapter():
    """Requirement 1: Every model in default allowed_models resolves to an implemented provider adapter."""
    settings = Settings()
    implemented_providers = {"mock", "ollama"}

    for model_id in settings.allowed_models:
        provider = get_provider_for_model(model_id, settings)
        assert provider is not None, f"Model '{model_id}' failed to resolve to a provider adapter."
        assert provider.name in implemented_providers, (
            f"Model '{model_id}' resolved to unsupported provider '{provider.name}'"
        )


def test_retired_models_rejected_at_route_and_failover(app, client: TestClient, test_settings: Settings):
    """Requirement 2: Retired models cannot be selected for new requests or chosen as failover candidates."""
    # Even if an operator places a retired model in allowed_models in production, route must reject it
    custom_settings = test_settings.model_copy(
        update={
            "app_env": "production",
            "allowed_models": test_settings.allowed_models + ["claude-3-7-sonnet-20250219", "gemini-1.5-flash"],
        }
    )
    app.dependency_overrides[get_settings] = lambda: custom_settings

    try:
        # Route rejection for claude-3-7-sonnet-20250219
        resp1 = client.post(
            "/v1/chat/completions",
            json={"model": "claude-3-7-sonnet-20250219", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp1.status_code == 400
        assert "retired or deprecated" in resp1.json()["error"]["message"]

        # Route rejection for gemini-1.5-flash
        resp2 = client.post(
            "/v1/chat/completions",
            json={"model": "gemini-1.5-flash", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp2.status_code == 400
        assert "retired or deprecated" in resp2.json()["error"]["message"]

        # Failover candidate rejection
        valid1, reason1 = validate_fallback_model("claude-3-7-sonnet-20250219", custom_settings)
        assert valid1 is False
        assert "retired or deprecated" in reason1

        valid2, reason2 = validate_fallback_model("gemini-1.5-flash", custom_settings)
        assert valid2 is False
        assert "retired or deprecated" in reason2

    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_restricted_legacy_models_follow_access_policy(app, client: TestClient, test_settings: Settings):
    """Requirement 3: Restricted legacy models require explicit allow_restricted_models=True."""
    # Scenario A: In allowed_models, but allow_restricted_models=False (default) -> REJECT
    settings_blocked = test_settings.model_copy(
        update={
            "allowed_models": test_settings.allowed_models + ["gemini-2.5-flash"],
            "allow_restricted_models": False,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings_blocked

    try:
        resp_blocked = client.post(
            "/v1/chat/completions",
            json={"model": "gemini-2.5-flash", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp_blocked.status_code == 400
        assert "restricted legacy model" in resp_blocked.json()["error"]["message"]

        # Failover rejects restricted model when policy is false
        valid_fb, reason_fb = validate_fallback_model("gemini-2.5-flash", settings_blocked)
        assert valid_fb is False
        assert "restricted legacy" in reason_fb or "ALLOW_RESTRICTED_MODELS" in reason_fb
    finally:
        app.dependency_overrides.pop(get_settings, None)

    # Scenario B: In allowed_models, and allow_restricted_models=True -> PERMIT
    settings_allowed = test_settings.model_copy(
        update={
            "allowed_models": test_settings.allowed_models + ["gemini-2.5-flash"],
            "allow_restricted_models": True,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings_allowed

    try:
        # Failover permits restricted model when policy is true
        valid_ok, reason_ok = validate_fallback_model("gemini-2.5-flash", settings_allowed)
        assert valid_ok is True
        assert reason_ok == "valid"
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_reference_unsupported_openai_model_rejected(app, client: TestClient, test_settings: Settings):
    """Requirement 4: gpt-4o-mini is strictly reference-only and cannot be executed."""
    engine = PricingEngine()
    meta = engine.models.get("gpt-4o-mini")
    assert meta is not None
    assert meta.get("status") == "reference_unsupported"

    cap = get_model_capabilities("gpt-4o-mini")
    assert cap is not None
    assert cap.status == "reference_unsupported"
    assert cap.supports_text is False

    # Direct provider routing raises InvalidModelError
    with pytest.raises(InvalidModelError, match="No provider adapter implemented"):
        get_provider_for_model("gpt-4o-mini", test_settings)

    # Route rejects execution even if placed in allowed_models
    custom_settings = test_settings.model_copy(
        update={"allowed_models": test_settings.allowed_models + ["gpt-4o-mini"]}
    )
    app.dependency_overrides[get_settings] = lambda: custom_settings

    try:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 400
        assert "reference catalog entry and has no implemented provider adapter" in resp.json()["error"]["message"]

        # Failover rejects reference models
        valid, reason = validate_fallback_model("gpt-4o-mini", custom_settings)
        assert valid is False
        assert "reference catalog entry" in reason
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_pricing_and_capabilities_agree_for_all_selectable_models():
    """Requirement 5: Pricing catalog and capability registry entries agree for all selectable models."""
    settings = Settings()
    engine = PricingEngine()

    for model_id in settings.allowed_models:
        pricing_meta = engine.models.get(model_id)
        assert pricing_meta is not None, f"Model '{model_id}' missing from pricing catalog."
        assert pricing_meta.get("status") == "active", (
            f"Selectable model '{model_id}' must have pricing status 'active', got '{pricing_meta.get('status')}'"
        )

        cap = get_model_capabilities(model_id)
        assert cap is not None, f"Model '{model_id}' missing from capability registry."
        assert cap.status == "active", (
            f"Selectable model '{model_id}' must have capability status 'active', got '{cap.status}'"
        )

        # Provider matches
        assert pricing_meta.get("provider") == cap.provider, (
            f"Provider mismatch for '{model_id}': pricing says '{pricing_meta.get('provider')}', capabilities says '{cap.provider}'"
        )


def test_historical_billing_records_remain_interpretable():
    """Requirement 6: Historical models and prices remain accurately computable."""
    engine = PricingEngine()

    # All known historical models compute Decimal cost without error
    historical_cases = [
        ("claude-3-7-sonnet-20250219", 10_000, 2_000, "claude", Decimal("0.060000")),
        ("claude-3-5-haiku-20241022", 10_000, 2_000, "claude", Decimal("0.016000")),
        ("claude-3-5-sonnet-20241022", 10_000, 2_000, "claude", Decimal("0.060000")),
        ("claude-3-haiku-20240307", 10_000, 2_000, "claude", Decimal("0.005000")),
        ("gemini-2.5-flash", 20_000, 10_000, "gemini", Decimal("0.031000")),
        ("gemini-2.5-pro", 20_000, 10_000, "gemini", Decimal("0.125000")),
        ("gemini-1.5-flash", 20_000, 10_000, "gemini", Decimal("0.004500")),
        ("gemini-1.5-pro", 20_000, 10_000, "gemini", Decimal("0.075000")),
        ("gpt-4o-mini", 10_000, 2_000, "openai", Decimal("0.002700")),
    ]

    for model, in_tok, out_tok, prov, expected_cost in historical_cases:
        res = engine.calculate_cost(model, in_tok, out_tok, provider=prov)
        assert res.calculation_status == "calculated", f"Failed to calculate historical cost for {model}"
        assert res.total_cost == expected_cost, f"Cost mismatch for {model}: expected {expected_cost}, got {res.total_cost}"


def test_unknown_and_unverified_models_fail_safely():
    """Requirement 7: Unknown models without capability entries fail safely (no tools, no streaming)."""
    assert model_supports_tools("completely-unknown-custom-model") is False
    assert model_supports_streaming("completely-unknown-custom-model") is False
    assert model_supports_streaming_tools("completely-unknown-custom-model") is False
