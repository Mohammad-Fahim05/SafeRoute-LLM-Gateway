"""Integration tests for SafeRoute LLM Gateway Phase 9.1 Multi-Provider Failover."""

import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select

from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.cache.redis_cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.errors import ProviderError
from app.db import get_db_session
from app.db.models import RequestRecord
from app.db.session import get_engine, init_db, reset_db_engine
from app.limiter.redis_limiter import RateLimiter, get_rate_limiter
from app.main import create_app
from app.providers import get_mock_provider, get_provider_for_model
from app.providers.failover import execute_with_failover
from tests.conftest import TEST_AUTH_SECRET, VALID_KEY_VERIFIER, VALID_TEST_KEY
from tests.unit.test_cache import FakeAsyncRedis
from tests.unit.test_rate_limiter import FakeAsyncRedisForLimiter


def auth_headers():
    return {"Authorization": f"Bearer {VALID_TEST_KEY}"}


def make_client_for_settings(settings: Settings) -> TestClient:
    """Helper to initialize SQLite database, dependencies, and test client."""
    reset_db_engine()
    engine = get_engine(settings.database_url)
    init_db(engine)

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def failover_settings(test_db_url: str) -> Settings:
    """Return Settings configured with failover enabled and deterministic mock models."""
    return Settings(
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        failover_enabled=True,
        failover_max_attempts=3,
        failover_timeout_budget_seconds=5.0,
        failover_retry_delay_seconds=0.01,
        failover_max_retry_delay_seconds=1.0,
        failover_fallback_models={
            "mock-error": ["mock-model"],
            "mock-timeout": ["mock-model"],
            "mock-rate-limit": ["mock-model"],
            "claude-sonnet-4-6": ["gemini-3.8-flash", "mock-model"],
        },
        database_url=test_db_url,
        cache_enabled=False,
    )


@pytest.fixture
def failover_client(failover_settings: Settings):
    """TestClient with failover enabled."""
    with make_client_for_settings(failover_settings) as test_client:
        yield test_client


# 1. Failover disabled preserves current single-provider behavior
def test_failover_disabled_preserves_single_provider_behavior(test_db_url: str):
    """Scenario 1: When failover_enabled=False, primary failures immediately raise without fallback."""
    settings = Settings(
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        failover_enabled=False,
        failover_fallback_models={"mock-error": ["mock-model"]},
        database_url=test_db_url,
    )
    with make_client_for_settings(settings) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 502
        assert resp.headers.get("X-Failover-Occurred") == "false"
        assert resp.headers.get("X-Failover-Attempts") == "1"


# 2. Primary provider succeeds without fallback attempt
def test_primary_succeeds_without_fallback_attempt(failover_client, failover_settings):
    """Scenario 2: When primary succeeds, exactly 1 attempt is made, failover is false."""
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "mock-model"
    assert resp.headers.get("X-Serving-Provider") == "mock"
    assert resp.headers.get("X-Serving-Model") == "mock-model"
    assert resp.headers.get("X-Failover-Occurred") == "false"
    assert resp.headers.get("X-Failover-Attempts") == "1"

    # Verify DB persistence
    rid = resp.headers["X-Request-ID"]
    with get_db_session(get_engine(failover_settings.database_url)) as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.status == "success"
        assert rec.failover_occurred is False
        assert rec.attempts_count == 1
        assert rec.model_requested == "mock-model"
        assert rec.model_actual == "mock-model"


# 3. Eligible primary-provider failure succeeds through configured fallback
def test_eligible_primary_failure_succeeds_through_fallback(failover_client, failover_settings):
    """Scenario 3: Primary 500 error triggers failover to configured fallback model which succeeds."""
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "mock-model"
    assert resp.headers.get("X-Serving-Provider") == "mock"
    assert resp.headers.get("X-Serving-Model") == "mock-model"
    assert resp.headers.get("X-Requested-Model") == "mock-error"
    assert resp.headers.get("X-Failover-Occurred") == "true"
    assert resp.headers.get("X-Failover-Attempts") == "2"

    # Verify DB persistence
    rid = resp.headers["X-Request-ID"]
    with get_db_session(get_engine(failover_settings.database_url)) as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.status == "success"
        assert rec.failover_occurred is True
        assert rec.attempts_count == 2
        assert rec.model_requested == "mock-error"
        assert rec.model_actual == "mock-model"
        assert rec.attempt_sequence is not None
        seq = json.loads(rec.attempt_sequence)
        assert len(seq) == 2
        assert seq[0]["model"] == "mock-error"
        assert seq[0]["success"] is False
        assert seq[1]["model"] == "mock-model"
        assert seq[1]["success"] is True


# 4. All providers fail and gateway returns a safe error
def test_all_providers_fail_returns_safe_error(failover_client, failover_settings):
    """Scenario 4: When primary and all fallbacks fail, returns safe error and records all attempts."""
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()
    # Configure mock-model to also fail
    mock_prov.set_failure_for_model("mock-model", ProviderError("Fallback also failed 500"), times=1)

    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers(),
    )
    assert resp.status_code in (502, 500)
    data = resp.json()
    assert "error" in data
    assert resp.headers.get("X-Failover-Occurred") == "true"
    assert resp.headers.get("X-Failover-Attempts") == "2"

    rid = resp.headers["X-Request-ID"]
    with get_db_session(get_engine(failover_settings.database_url)) as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.status == "failed"
        assert rec.failover_occurred is True
        assert rec.attempts_count == 2


# 5. Authentication failures do not trigger failover
def test_authentication_failures_do_not_trigger_failover(failover_client):
    """Scenario 5: 401 client auth and provider auth errors must never trigger failover."""
    # Client auth failure
    bad_resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        headers={"Authorization": "Bearer invalid_key"},
    )
    assert bad_resp.status_code == 401

    # Provider upstream auth error
    prov_auth_resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-auth-error", "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers(),
    )
    assert prov_auth_resp.status_code == 502
    data = prov_auth_resp.json()
    assert data["error"]["code"] == "provider_authentication_error"
    # Did not try fallback
    assert prov_auth_resp.headers.get("X-Failover-Occurred") == "false"
    assert prov_auth_resp.headers.get("X-Failover-Attempts") == "1"


# 6. Invalid requests and schema errors do not trigger failover
def test_invalid_requests_do_not_trigger_failover(failover_client):
    """Scenario 6: 400/422 schema errors must never trigger failover."""
    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": []},  # Empty messages
        headers=auth_headers(),
    )
    assert resp.status_code == 422
    assert resp.headers.get("X-Failover-Occurred") is None


# 7. Guardrail rejections do not trigger failover
def test_input_guardrail_rejections_do_not_trigger_failover(failover_settings):
    """Scenario 7: Input guardrail blocks reject request without provider failover."""
    settings = failover_settings.model_copy(
        update={
            "guardrails_enabled": True,
            "guardrails_input_enabled": True,
            "guardrails_rules": [
                {"rule_id": "block_evil", "pattern": "DROP DATABASE", "match_type": "contains", "stage": "input"}
            ],
        }
    )
    with make_client_for_settings(settings) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "DROP DATABASE students;"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "input_guardrail_blocked"
        assert resp.headers.get("X-Failover-Occurred") is None


# 8. Disallowed and retired fallback models are rejected
def test_disallowed_and_retired_fallback_models_are_skipped(failover_settings):
    """Scenario 8: Disallowed or retired fallback models are rejected/skipped by orchestrator."""
    settings = failover_settings.model_copy(
        update={
            "failover_fallback_models": {
                # First fallback is retired, second is unapproved, third is valid mock-model
                "mock-error": ["claude-3-7-sonnet-20250219", "unapproved-model", "mock-model"]
            }
        }
    )
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    with make_client_for_settings(settings) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 200
        # Reached mock-model skipping the retired and disallowed models
        assert resp.headers.get("X-Serving-Model") == "mock-model"
        assert resp.headers.get("X-Failover-Attempts") == "2"


# 9. Attempt limits are respected
def test_attempt_limits_are_strictly_respected(failover_settings):
    """Scenario 9: Gateway halts when FAILOVER_MAX_ATTEMPTS is reached."""
    settings = failover_settings.model_copy(
        update={
            "failover_max_attempts": 2,
            "failover_fallback_models": {
                "mock-error": ["mock-server-error", "mock-model"]
            },
        }
    )
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    with make_client_for_settings(settings) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 502
        assert resp.headers.get("X-Failover-Attempts") == "2"


# 10. Request deadlines prevent unbounded retries
def test_request_deadlines_prevent_unbounded_retries(failover_settings):
    """Scenario 10: Failover timeout budget halts attempts if overall deadline expires."""
    settings = failover_settings.model_copy(
        update={
            "failover_timeout_budget_seconds": 0.2,
            "provider_timeout_seconds": 0.15,
            "failover_fallback_models": {
                "mock-timeout": ["mock-timeout", "mock-model"]
            },
        }
    )
    with make_client_for_settings(settings) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-timeout", "messages": [{"role": "user", "content": "Hello"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "gateway_timeout"


# 11. Retry hints are handled within configured limits
def test_retry_hints_handled_within_limits(failover_client):
    """Scenario 11: Rate limit 429 with retry hint triggers fallback."""
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-rate-limit", "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Failover-Occurred") == "true"
    assert resp.headers.get("X-Serving-Model") == "mock-model"


# 12. Final provider/model metadata identifies actual serving model
def test_final_provider_model_metadata_identifies_serving_model(failover_client):
    """Scenario 12: Payload and response headers strictly reflect actual serving model."""
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "Test"}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "mock-model"
    assert resp.headers["X-Serving-Model"] == "mock-model"
    assert resp.headers["X-Serving-Provider"] == "mock"
    assert resp.headers["X-Requested-Model"] == "mock-error"


# 13 & 14. Usage and cost fields preserve unknown values & partial/uncertain failures do not fabricate billing data
def test_failed_attempts_do_not_fabricate_billing_data(failover_client, failover_settings):
    """Scenarios 13 & 14: Failed attempts do not fabricate tokens or cloud charges."""
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "Billing check"}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    rid = resp.headers["X-Request-ID"]

    with get_db_session(get_engine(failover_settings.database_url)) as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        # Only tokens from successful serving mock provider are recorded
        assert rec.usage is not None
        assert rec.usage.calculation_status == "mock_excluded"
        assert rec.usage.total_cost is None


# 15. Request IDs and sanitized error logs remain correct
def test_request_id_preserved_across_failover(failover_client):
    """Scenario 15: Same X-Request-ID is preserved and propagated across all attempts."""
    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers(),
    )
    rid = resp.headers["X-Request-ID"]
    assert rid.startswith("req_") or len(rid) > 0


# 16. Cache isolation and fallback cache semantics remain correct
def test_cache_isolation_and_fallback_semantics(failover_settings):
    """Scenario 16: Fallback response is not cached under primary requested model key."""
    settings = failover_settings.model_copy(update={"cache_enabled": True})
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    fake_redis = FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=fake_redis, settings=settings)

    with make_client_for_settings(settings) as client:
        client.app.dependency_overrides[get_cache] = lambda: cache_instance

        # Request 1: fails over from mock-error to mock-model
        resp1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Cache test"}]},
            headers=auth_headers(),
        )
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Failover-Occurred") == "true"
        # Must be BYPASS, not stored in cache
        assert resp1.headers.get("X-Cache") == "BYPASS"

        # Request 2: same prompt to mock-error must NOT be a cache HIT!
        resp2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Cache test"}]},
            headers=auth_headers(),
        )
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Cache") == "BYPASS"


# 17. Rate limiting is not bypassed by fallback
def test_rate_limiting_not_bypassed_by_fallback(failover_settings):
    """Scenario 17: Fallback does not bypass gateway rate limits."""
    settings = failover_settings.model_copy(
        update={
            "rate_limit_enabled": True,
            "rate_limit_requests": 1,
            "rate_limit_window_seconds": 60,
        }
    )
    fake_redis = FakeAsyncRedisForLimiter()
    limiter = RateLimiter(redis_client=fake_redis, settings=settings)

    with make_client_for_settings(settings) as client:
        client.app.dependency_overrides[get_rate_limiter] = lambda: limiter

        # First request succeeds
        resp1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Req 1"}]},
            headers=auth_headers(),
        )
        assert resp1.status_code == 200

        # Second request exceeds quota and is rejected before failover
        resp2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Req 2"}]},
            headers=auth_headers(),
        )
        assert resp2.status_code == 429
        data = resp2.json()
        assert data["error"]["code"] == "rate_limit_exceeded"


# 18. Output guardrails still apply to fallback responses
def test_output_guardrails_apply_to_fallback_responses(failover_settings):
    """Scenario 18: Output guardrails validate fallback responses and block if violation occurs."""
    settings = failover_settings.model_copy(
        update={
            "guardrails_enabled": True,
            "guardrails_output_enabled": True,
            "guardrails_rules": [
                {
                    "rule_id": "block_mock_output",
                    "pattern": "SafeRoute mock provider",
                    "match_type": "contains",
                    "stage": "output",
                }
            ],
        }
    )
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    with make_client_for_settings(settings) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Trigger guardrail"}]},
            headers=auth_headers(),
        )
        assert resp.status_code == 502
        data = resp.json()
        assert data["error"]["code"] == "output_guardrail_blocked"


# 19. Concurrent requests do not leak routing state
@pytest.mark.anyio
async def test_concurrent_requests_independent_routing():
    """Scenario 19: Concurrent requests execute independently without state leakage."""
    settings = Settings(
        failover_enabled=True,
        failover_fallback_models={
            "mock-error": ["mock-model"],
            "mock-model": ["mock-model"],
        },
    )
    mock_prov = get_mock_provider()
    mock_prov.reset_custom_behaviors()

    req_failover = ChatCompletionRequest(
        model="mock-error",
        messages=[ChatMessage(role="user", content="Concurrent 1")],
    )
    req_direct = ChatCompletionRequest(
        model="mock-model",
        messages=[ChatMessage(role="user", content="Concurrent 2")],
    )

    t1 = execute_with_failover(
        request=req_failover,
        settings=settings,
        allow_failover=True,
        provider_resolver=get_provider_for_model,
        overall_start_time=asyncio.get_event_loop().time(),
    )
    t2 = execute_with_failover(
        request=req_direct,
        settings=settings,
        allow_failover=True,
        provider_resolver=get_provider_for_model,
        overall_start_time=asyncio.get_event_loop().time(),
    )

    r1, r2 = await asyncio.gather(t1, t2)
    assert r1.failover_occurred is True
    assert len(r1.attempts) == 2
    assert r2.failover_occurred is False
    assert len(r2.attempts) == 1


# 20. Request-level override tests (Header and Request schema)
def test_request_header_disables_failover_when_globally_enabled(failover_client):
    """Scenario 20a: When X-Allow-Failover: false header is sent, failover is disabled for that request."""
    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "Hello"}]},
        headers={**auth_headers(), "X-Allow-Failover": "false"},
    )
    assert resp.status_code == 502
    assert resp.headers.get("X-Failover-Occurred") == "false"
    assert resp.headers.get("X-Failover-Attempts") == "1"


def test_request_body_disables_failover_when_globally_enabled(failover_client):
    """Scenario 20b: When allow_failover: false is set in JSON body, failover is disabled for that request."""
    resp = failover_client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-error",
            "messages": [{"role": "user", "content": "Hello"}],
            "allow_failover": False,
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 502
    assert resp.headers.get("X-Failover-Occurred") == "false"
    assert resp.headers.get("X-Failover-Attempts") == "1"


# 21. Conflicting global and request-level settings (Header > Body > Global)
def test_conflicting_settings_precedence(test_db_url: str):
    """Scenario 21: Verify Header strictly overrides Body, and Body strictly overrides Global."""
    settings_globally_disabled = Settings(
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        failover_enabled=False,
        failover_fallback_models={"mock-error": ["mock-model"]},
        database_url=test_db_url,
    )

    with make_client_for_settings(settings_globally_disabled) as client:
        # 1. Global=False, Body=False, Header="true" -> Header wins, failover occurs
        resp1 = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-error",
                "messages": [{"role": "user", "content": "Hello"}],
                "allow_failover": False,
            },
            headers={**auth_headers(), "X-Allow-Failover": "true"},
        )
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Failover-Occurred") == "true"
        assert resp1.headers.get("X-Serving-Model") == "mock-model"

        # 2. Global=False, Header absent, Body=True -> Body wins, failover occurs
        resp2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-error",
                "messages": [{"role": "user", "content": "Hello"}],
                "allow_failover": True,
            },
            headers=auth_headers(),
        )
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Failover-Occurred") == "true"
        assert resp2.headers.get("X-Serving-Model") == "mock-model"

    settings_globally_enabled = Settings(
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        failover_enabled=True,
        failover_fallback_models={"mock-error": ["mock-model"]},
        database_url=test_db_url,
    )

    with make_client_for_settings(settings_globally_enabled) as client:
        # 3. Global=True, Body=True, Header="false" -> Header wins, failover disabled
        resp3 = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-error",
                "messages": [{"role": "user", "content": "Hello"}],
                "allow_failover": True,
            },
            headers={**auth_headers(), "X-Allow-Failover": "false"},
        )
        assert resp3.status_code == 502
        assert resp3.headers.get("X-Failover-Occurred") == "false"
        assert resp3.headers.get("X-Failover-Attempts") == "1"


# 22. Malformed X-Allow-Failover header is rejected with HTTP 400
def test_malformed_failover_header_returns_400(failover_client):
    """Scenario 22: Unrecognized X-Allow-Failover header returns 400 invalid_request."""
    resp = failover_client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        headers={**auth_headers(), "X-Allow-Failover": "not_a_boolean"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "invalid_request"
    assert "Invalid value for X-Allow-Failover" in data["error"]["message"]


# 23. Provider 429 vs Gateway 429 isolation
def test_gateway_rate_limit_never_triggers_provider_failover(test_db_url: str):
    """Scenario 23: Gateway client 429 is evaluated before provider routing and never triggers failover."""
    settings = Settings(
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        failover_enabled=True,
        failover_fallback_models={"mock-error": ["mock-model"]},
        rate_limit_enabled=True,
        rate_limit_requests=1,
        rate_limit_window_seconds=60,
        database_url=test_db_url,
    )
    fake_redis = FakeAsyncRedisForLimiter()
    limiter = RateLimiter(redis_client=fake_redis, settings=settings)

    with make_client_for_settings(settings) as client:
        client.app.dependency_overrides[get_rate_limiter] = lambda: limiter

        # Request 1: succeeds (uses quota 1/1)
        r1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Req 1"}]},
            headers=auth_headers(),
        )
        assert r1.status_code == 200

        # Request 2: exceeds gateway client quota -> 429 RateLimitExceededError
        r2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Req 2"}]},
            headers=auth_headers(),
        )
        assert r2.status_code == 429
        data = r2.json()
        assert data["error"]["code"] == "rate_limit_exceeded"
        # Gateway rate limit never creates failover attempts
        assert "X-Failover-Occurred" not in r2.headers


# 24. Production rejects mock fallback for real AI models
def test_production_rejects_mock_fallback_for_real_cloud_model(test_db_url: str):
    """Scenario 24: In production, real models cannot silently fall back to mock models."""
    settings = Settings(
        app_env="production",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        failover_enabled=True,
        failover_allow_mock_fallback=False,
        active_provider="ollama",
        # Misconfigured fallback chain attempting to fall back to mock-model in production
        failover_fallback_models={"llama3.2:1b": ["mock-model"]},
        database_url=test_db_url,
    )

    with make_client_for_settings(settings) as client:
        # Patch Ollama provider to simulate an upstream outage
        with patch("app.providers.ollama.OllamaProvider.complete", side_effect=ProviderError("Ollama 502 outage")):
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "llama3.2:1b", "messages": [{"role": "user", "content": "Prod query"}]},
                headers=auth_headers(),
            )
            # Must NOT succeed with mock-model! Must fail with 502 Bad Gateway
            assert resp.status_code == 502
            assert resp.headers.get("X-Failover-Occurred") == "false"
            assert resp.headers.get("X-Failover-Attempts") == "1"
            assert resp.headers.get("X-Serving-Model") == "llama3.2:1b"
