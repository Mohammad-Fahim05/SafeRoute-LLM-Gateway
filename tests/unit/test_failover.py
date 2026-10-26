"""Unit tests for failover error classification, model validation, and configuration."""

import asyncio
import pytest
import httpx

from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.config import Settings
from app.core.errors import (
    AppException,
    AuthenticationError,
    InputGuardrailBlockedError,
    InvalidModelError,
    OutputGuardrailBlockedError,
    PayloadTooLargeError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitExceededError,
    UnsupportedParameterError,
)
from app.pricing.calculator import pricing_engine
from app.providers import get_mock_provider, get_provider_for_model
from app.providers.failover import (
    FailoverAttempt,
    classify_failure,
    execute_with_failover,
    validate_fallback_model,
)


def test_classification_eligible_transient_errors():
    """Verify transient errors (timeouts, rate limits, 5xx server errors, connection failures) are classified as eligible."""
    settings = Settings()

    # Timeouts
    is_eligible, cat, hint = classify_failure(ProviderTimeoutError("timeout"), settings)
    assert is_eligible is True
    assert cat == "timeout"
    assert hint is None

    is_eligible, cat, _ = classify_failure(asyncio.TimeoutError(), settings)
    assert is_eligible is True
    assert cat == "timeout"

    is_eligible, cat, _ = classify_failure(httpx.TimeoutException("httpx timeout"), settings)
    assert is_eligible is True
    assert cat == "timeout"

    # Rate limits with retry hints
    is_eligible, cat, hint = classify_failure(
        ProviderRateLimitError("429 rate limit", retry_after=1.5), settings
    )
    assert is_eligible is True
    assert cat == "rate_limit"
    assert hint == 1.5

    # Upstream httpx HTTPStatusError 429 with Retry-After header
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp_429 = httpx.Response(429, headers={"retry-after": "2.5"}, request=req)
    http_429_err = httpx.HTTPStatusError("Rate limited", request=req, response=resp_429)
    is_eligible, cat, hint = classify_failure(http_429_err, settings)
    assert is_eligible is True
    assert cat == "rate_limit"
    assert hint == 2.5

    # 5xx Provider errors
    is_eligible, cat, _ = classify_failure(ProviderError("502 Bad Gateway"), settings)
    assert is_eligible is True
    assert cat == "provider_server_error"

    # 503 Provider Unavailable with retry hint
    is_eligible, cat, hint = classify_failure(
        ProviderUnavailableError("503 Overloaded", retry_after=3.0), settings
    )
    assert is_eligible is True
    assert cat == "provider_server_error"
    assert hint == 3.0

    # Malformed response
    is_eligible, cat, _ = classify_failure(
        ProviderMalformedResponseError("bad json"), settings
    )
    assert is_eligible is True
    assert cat == "malformed_response"

    # Connection failures
    is_eligible, cat, _ = classify_failure(httpx.ConnectError("refused"), settings)
    assert is_eligible is True
    assert cat == "connection_failure"


def test_classification_ineligible_errors():
    """Verify non-transient errors (auth, schema, guardrails, client errors, gateway rate limits) are ineligible."""
    settings = Settings()

    # Provider and Client Authentication
    is_eligible, cat, _ = classify_failure(
        ProviderAuthenticationError("401 bad key"), settings
    )
    assert is_eligible is False
    assert cat == "ineligible_authentication"

    is_eligible, cat, _ = classify_failure(AuthenticationError("missing key"), settings)
    assert is_eligible is False
    assert cat == "ineligible_authentication"

    # Gateway rate limits must be ineligible and classified as gateway rate limits
    from app.core.errors import RateLimiterUnavailableError

    is_eligible, cat, _ = classify_failure(RateLimitExceededError("quota exceeded"), settings)
    assert is_eligible is False
    assert cat == "ineligible_gateway_rate_limit"

    is_eligible, cat, _ = classify_failure(RateLimiterUnavailableError("limiter down"), settings)
    assert is_eligible is False
    assert cat == "ineligible_gateway_rate_limit"

    # Client Request and Schema errors
    for err in [
        InvalidModelError("disallowed"),
        UnsupportedParameterError("stream: true"),
        PayloadTooLargeError("too large"),
    ]:
        is_eligible, cat, _ = classify_failure(err, settings)
        assert is_eligible is False
        assert cat == "ineligible_client_error"

    # Guardrail blocks (both input and output)
    is_eligible, cat, _ = classify_failure(
        InputGuardrailBlockedError("blocked prompt"), settings
    )
    assert is_eligible is False
    assert cat == "ineligible_guardrail"

    is_eligible, cat, _ = classify_failure(
        OutputGuardrailBlockedError("blocked response"), settings
    )
    assert is_eligible is False
    assert cat == "ineligible_guardrail"

    # Unknown unclassified exceptions
    is_eligible, cat, _ = classify_failure(ValueError("unexpected value error"), settings)
    assert is_eligible is False
    assert cat == "unknown_unclassified"


def test_validate_fallback_model():
    """Verify fallback models are validated against allowlist, retired catalog status, and mock restrictions."""
    settings = Settings(
        app_env="production",
        failover_allow_mock_fallback=False,
        allowed_models=["mock-model", "llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M", "claude-3-7-sonnet-20250219"],
    )

    # Active real model passes as fallback for real model
    valid, reason = validate_fallback_model(
        "qwen2.5-coder:7b-instruct-q4_K_M", settings, requested_model="llama3.2:1b"
    )
    assert valid is True
    assert reason == "valid"

    # In production, mock fallback for a real model is strictly rejected
    valid, reason = validate_fallback_model(
        "mock-model", settings, requested_model="llama3.2:1b"
    )
    assert valid is False
    assert "cannot serve as fallback for real model" in reason

    # In development, mock fallback for a real model is rejected if failover_allow_mock_fallback=False
    dev_settings_strict = Settings(
        app_env="development",
        failover_allow_mock_fallback=False,
        allowed_models=["mock-model", "llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M"],
    )
    valid, reason = validate_fallback_model(
        "mock-model", dev_settings_strict, requested_model="llama3.2:1b"
    )
    assert valid is False
    assert "FAILOVER_ALLOW_MOCK_FALLBACK is false" in reason

    # In development, mock fallback for real model is permitted if explicitly opted in
    dev_settings_optin = Settings(
        app_env="development",
        failover_allow_mock_fallback=True,
        allowed_models=["mock-model", "llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M"],
    )
    valid, reason = validate_fallback_model(
        "mock-model", dev_settings_optin, requested_model="llama3.2:1b"
    )
    assert valid is True
    assert reason == "valid"

    # Mock-to-mock fallback is permitted in all environments for testing
    prod_mock_to_mock = Settings(
        app_env="production",
        allowed_models=["mock-model", "mock-error"],
    )
    valid, reason = validate_fallback_model(
        "mock-model", prod_mock_to_mock, requested_model="mock-error"
    )
    assert valid is True
    assert reason == "valid"

    # Disallowed model fails
    valid, reason = validate_fallback_model("unapproved-model-xyz", settings)
    assert valid is False
    assert "not in allowed_models" in reason

    # Retired model from catalog fails even if present in allowed_models
    valid, reason = validate_fallback_model("claude-3-7-sonnet-20250219", settings)
    assert valid is False
    assert "retired or deprecated" in reason

    # Empty string fails
    valid, reason = validate_fallback_model("", settings)
    assert valid is False


def test_failover_config_parsing():
    """Verify parsing of failover configuration from dictionary, JSON string, or comma-separated values."""
    # JSON dictionary
    settings = Settings(
        failover_fallback_models='{"llama3.2:1b": ["qwen2.5-coder:7b-instruct-q4_K_M"], "default": ["mock-model"]}'
    )
    assert settings.get_fallback_models_for("llama3.2:1b") == ["qwen2.5-coder:7b-instruct-q4_K_M"]
    assert settings.get_fallback_models_for("other-model") == ["mock-model"]

    # Comma-separated list for default
    settings_csv = Settings(failover_fallback_models="llama3.2:1b,mock-model")
    assert settings_csv.get_fallback_models_for("any-model") == ["llama3.2:1b", "mock-model"]

    # Status and error codes
    settings_codes = Settings(
        failover_eligible_status_codes="429,500,503",
        failover_eligible_error_codes="gateway_timeout,provider_error",
    )
    assert settings_codes.failover_eligible_status_codes == [429, 500, 503]
    assert settings_codes.failover_eligible_error_codes == ["gateway_timeout", "provider_error"]

    # Validation errors
    with pytest.raises(ValueError):
        Settings(failover_max_attempts=0)

    with pytest.raises(ValueError):
        Settings(failover_timeout_budget_seconds=-1.0)


@pytest.mark.anyio
async def test_execute_with_failover_success_primary():
    """When primary provider succeeds, only one attempt is executed."""
    settings = Settings(
        failover_enabled=True,
        failover_fallback_models={"mock-model": ["mock-model"]},
    )
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()
    mock_prov.reset_call_count()

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    res = await execute_with_failover(
        request=req,
        settings=settings,
        allow_failover=True,
        provider_resolver=get_provider_for_model,
        overall_start_time=asyncio.get_event_loop().time(),
    )

    assert res.response is not None
    assert res.failover_occurred is False
    assert len(res.attempts) == 1
    assert res.attempts[0].success is True
    assert res.serving_provider == "mock"
    assert res.serving_model == "mock-model"


@pytest.mark.anyio
async def test_execute_with_failover_respects_max_attempts():
    """Verify orchestrator halts when max_attempts is reached."""
    settings = Settings(
        failover_enabled=True,
        failover_max_attempts=2,
        failover_retry_delay_seconds=0.0,
        failover_fallback_models={"mock-error": ["mock-server-error", "mock-model"]},
    )
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    req = ChatCompletionRequest(
        model="mock-error",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    res = await execute_with_failover(
        request=req,
        settings=settings,
        allow_failover=True,
        provider_resolver=get_provider_for_model,
        overall_start_time=asyncio.get_event_loop().time(),
    )

    assert res.response is None
    assert len(res.attempts) == 2
    assert res.attempts[0].model == "mock-error"
    assert res.attempts[1].model == "mock-server-error"
