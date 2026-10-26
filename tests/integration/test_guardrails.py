"""Integration tests for input and output guardrails, HTTP responses, cache interactions, and SQLite persistence."""

import json
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select

from app.cache.redis_cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import get_db_session, init_db, reset_db_engine
from app.db.models import RequestRecord, UsageRecord
from app.db.session import get_engine
from app.guardrails import GuardrailEngine, get_guardrail_engine
from app.limiter.redis_limiter import RateLimiter, get_rate_limiter
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET
from tests.unit.test_cache import FakeAsyncRedis
from tests.unit.test_rate_limiter import FakeAsyncRedisForLimiter


def build_guardrail_test_setup(
    test_db_url: str,
    guardrails_enabled: bool = True,
    guardrails_rules: list = None,
    guardrails_input_enabled: bool = True,
    guardrails_output_enabled: bool = True,
    cache_enabled: bool = False,
    rate_limit_enabled: bool = False,
    rate_limit_requests: int = 10,
):
    """Helper to initialize test environment with in-memory SQLite, mock Redis, and guardrail settings."""
    key_alice = "gw_test_alice_key_11111111111111111111"
    verifier_alice = compute_key_verifier(key_alice, TEST_AUTH_SECRET)

    rules = guardrails_rules if guardrails_rules is not None else [
        {
            "rule_id": "block_prohibited_prompt",
            "pattern": r"(DROP\s+DATABASE|MALICIOUS_PROMPT)",
            "match_type": "regex",
            "stage": "input",
        },
        {
            "rule_id": "block_leaked_secret",
            "pattern": "SECRET_LEAK_TOKEN",
            "match_type": "contains",
            "stage": "output",
        },
    ]

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[
            {"client_id": "alice", "verifier": verifier_alice, "enabled": True},
        ],
        allowed_models=["mock-model", "mock-error", "mock-timeout", "mock-malformed"],
        database_url=test_db_url,
        # Guardrails settings
        guardrails_enabled=guardrails_enabled,
        guardrails_input_enabled=guardrails_input_enabled,
        guardrails_output_enabled=guardrails_output_enabled,
        guardrails_action="block",
        guardrails_max_text_length=100_000,
        guardrails_rules=rules,
        # Cache settings
        cache_enabled=cache_enabled,
        cache_ttl_seconds=300,
        cache_namespace="v1",
        # Rate limit settings
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_requests=rate_limit_requests,
        rate_limit_window_seconds=60,
        rate_limit_namespace="v1",
        rate_limit_failure_policy="fail_closed",
        provider_timeout_seconds=0.5,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_cache_redis = FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=fake_cache_redis, settings=settings)

    fake_limiter_redis = FakeAsyncRedisForLimiter()
    limiter_instance = RateLimiter(redis_client=fake_limiter_redis, settings=settings)

    guardrail_engine = GuardrailEngine(settings=settings)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: cache_instance
    app.dependency_overrides[get_rate_limiter] = lambda: limiter_instance
    app.dependency_overrides[get_guardrail_engine] = lambda: guardrail_engine

    return app, settings, fake_cache_redis, fake_limiter_redis, key_alice


def test_input_guardrail_allowed_request_passes(test_db_url: str):
    """Verify safe input prompt passes guardrail checks and receives HTTP 200."""
    app, settings, _, _, key_alice = build_guardrail_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "Tell me a joke about Python"}],
            },
        )
        assert resp.status_code == 200
        assert "choices" in resp.json()


def test_input_guardrail_blocks_prohibited_prompt_and_audits(test_db_url: str):
    """Verify input matching a block rule returns HTTP 400 without invoking provider, logged in DB."""
    from app.providers.mock import MockProvider

    app, settings, _, _, key_alice = build_guardrail_test_setup(test_db_url)

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Execute MALICIOUS_PROMPT now"}],
                },
            )
            # 1. HTTP 400 Bad Request
            assert resp.status_code == 400
            body = resp.json()
            assert body["error"]["code"] == "input_guardrail_blocked"
            assert body["error"]["type"] == "invalid_request_error"
            assert "blocked by input safety guardrails" in body["error"]["message"]
            assert "X-Request-ID" in resp.headers
            rid = resp.headers["X-Request-ID"]

            # 2. Provider was NEVER invoked
            assert call_count == 0

    # 3. SQLite audit record verification
    engine = get_engine(test_db_url)
    with get_db_session(engine) as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.http_status == 400
        assert rec.status == "failed"
        assert rec.error_code == "input_guardrail_blocked"
        assert rec.provider == "gateway"
        assert rec.client_id == "alice"
        # Privacy guarantee: error_message does not contain raw prompt text
        assert "MALICIOUS_PROMPT" not in rec.error_message

        # Token usage is zero/unavailable
        assert rec.usage.input_tokens is None
        assert rec.usage.output_tokens is None
        assert rec.usage.total_cost is None


def test_input_guardrail_consumes_rate_limit_quota(test_db_url: str):
    """Requirement: Rate limiting precedes guardrail evaluation. Blocked prompts consume quota."""
    app, settings, _, _, key_alice = build_guardrail_test_setup(
        test_db_url,
        rate_limit_enabled=True,
        rate_limit_requests=2,
    )

    bad_payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "MALICIOUS_PROMPT"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request 1: Blocked by input guardrails (consumes quota 1)
        r1 = client.post("/v1/chat/completions", json=bad_payload)
        assert r1.status_code == 400
        assert r1.json()["error"]["code"] == "input_guardrail_blocked"

        # Request 2: Blocked by input guardrails (consumes quota 2)
        r2 = client.post("/v1/chat/completions", json=bad_payload)
        assert r2.status_code == 400
        assert r2.json()["error"]["code"] == "input_guardrail_blocked"

        # Request 3: Rate limit exceeded! (Returns HTTP 429)
        r3 = client.post("/v1/chat/completions", json=bad_payload)
        assert r3.status_code == 429
        assert r3.json()["error"]["code"] == "rate_limit_exceeded"


def test_auth_and_schema_validation_precede_guardrails(test_db_url: str):
    """Authentication and schema/model checks fail before guardrails run."""
    app, settings, _, _, key_alice = build_guardrail_test_setup(test_db_url)

    with TestClient(app) as client:
        # 1. Auth failure -> 401
        r_auth = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "MALICIOUS_PROMPT"}]},
            headers={"Authorization": "Bearer gw_invalid_key_99999999999999999999"},
        )
        assert r_auth.status_code == 401
        assert r_auth.json()["error"]["code"] == "invalid_api_key"

        # 2. Invalid model -> 400 invalid_model
        r_model = client.post(
            "/v1/chat/completions",
            json={"model": "unauthorized-model", "messages": [{"role": "user", "content": "MALICIOUS_PROMPT"}]},
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert r_model.status_code == 400
        assert r_model.json()["error"]["code"] == "invalid_model"


def test_output_guardrail_blocks_prohibited_provider_completion(test_db_url: str):
    """Verify provider output violating guardrails returns HTTP 502, not cached, retains usage."""
    from app.providers.mock import MockProvider

    app, settings, fake_cache_redis, _, key_alice = build_guardrail_test_setup(
        test_db_url,
        cache_enabled=True,
    )

    # Mock provider response containing SECRET_LEAK_TOKEN
    orig_complete = MockProvider.complete

    async def leaking_complete(self, req):
        res = await orig_complete(self, req)
        res.choices[0].message.content = "Here is your data: SECRET_LEAK_TOKEN."
        return res

    with patch.object(MockProvider, "complete", leaking_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Tell me a secret"}],
                },
            )
            # 1. HTTP 502 Bad Gateway
            assert resp.status_code == 502
            body = resp.json()
            assert body["error"]["code"] == "output_guardrail_blocked"
            assert body["error"]["type"] == "bad_gateway_error"
            assert "blocked by output safety guardrails" in body["error"]["message"]
            rid = resp.headers["X-Request-ID"]

            # 2. Blocked response was NOT stored in Redis cache
            assert len(fake_cache_redis.store) == 0

    # 3. Verify SQLite audit record retains provider latency and genuine usage
    engine = get_engine(test_db_url)
    with get_db_session(engine) as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.http_status == 502
        assert rec.status == "failed"
        assert rec.error_code == "output_guardrail_blocked"
        assert rec.provider == "mock"
        # Provider was called: latency and tokens are recorded accurately!
        assert rec.provider_latency_ms is not None
        assert rec.usage.input_tokens is not None
        assert rec.usage.output_tokens is not None


def test_output_guardrail_blocks_stale_cache_hit_and_invalidates(test_db_url: str):
    """Verify a stale cached response violating newly introduced output guardrails is deleted and blocked."""
    app, settings, fake_cache_redis, _, key_alice = build_guardrail_test_setup(
        test_db_url,
        cache_enabled=True,
        guardrails_rules=[{"rule_id": "block_mock_text", "pattern": "deterministic response", "match_type": "contains", "stage": "output"}],
    )

    # First request: disable guardrails temporarily to seed the cache with default mock response
    settings.guardrails_enabled = False
    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        r1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Test prompt"}]},
        )
        assert r1.status_code == 200
        assert r1.headers["X-Cache"] == "MISS"
        # Cache now contains the entry
        assert len(fake_cache_redis.store) == 1

    # Re-enable guardrails with output rule blocking "Mock LLM output"
    settings.guardrails_enabled = True

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Second request: Cache HIT occurs, but output guardrail intercepts the cached response!
        r2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Test prompt"}]},
        )
        assert r2.status_code == 502
        assert r2.json()["error"]["code"] == "output_guardrail_blocked"

        # The stale cache entry was invalidated / deleted from Redis!
        assert len(fake_cache_redis.deleted_keys) > 0


def test_guardrails_disabled_permits_prohibited_terms(test_db_url: str):
    """When GUARDRAILS_ENABLED=false, content checks are skipped completely."""
    app, settings, _, _, key_alice = build_guardrail_test_setup(
        test_db_url,
        guardrails_enabled=False,
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "MALICIOUS_PROMPT"}],
            },
        )
        assert resp.status_code == 200
