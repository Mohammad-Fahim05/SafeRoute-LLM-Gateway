"""Integration tests for Redis-backed client rate limiting, HTTP 429 behavior, headers, and SQLite persistence."""

import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select
from redis.exceptions import ConnectionError

from app.api.schemas import ChatCompletionResponse
from app.cache.redis_cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import get_db_session, init_db, reset_db_engine
from app.db.models import RequestRecord, UsageRecord
from app.db.session import get_engine
from app.limiter.redis_limiter import RateLimiter, get_rate_limiter
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET
from tests.unit.test_cache import FakeAsyncRedis
from tests.unit.test_rate_limiter import FakeAsyncRedisForLimiter


def build_rate_limit_test_setup(
    test_db_url: str,
    rate_limit_enabled: bool = True,
    rate_limit_requests: int = 2,
    rate_limit_window_seconds: int = 60,
    rate_limit_failure_policy: str = "fail_closed",
    cache_enabled: bool = False,
):
    """Helper to initialize test environment with in-memory SQLite and fake Redis."""
    key_alice = "gw_test_alice_key_11111111111111111111"
    key_bob = "gw_test_bob_key_2222222222222222222222"

    verifier_alice = compute_key_verifier(key_alice, TEST_AUTH_SECRET)
    verifier_bob = compute_key_verifier(key_bob, TEST_AUTH_SECRET)

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[
            {"client_id": "alice", "verifier": verifier_alice, "enabled": True},
            {"client_id": "bob", "verifier": verifier_bob, "enabled": True},
        ],
        allowed_models=["mock-model", "mock-error", "mock-timeout", "mock-malformed"],
        active_provider="mock",
        database_url=test_db_url,
        # Cache settings
        cache_enabled=cache_enabled,
        cache_ttl_seconds=300,
        cache_namespace="v1",
        # Rate limit settings
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_requests=rate_limit_requests,
        rate_limit_window_seconds=rate_limit_window_seconds,
        rate_limit_namespace="v1",
        rate_limit_failure_policy=rate_limit_failure_policy,
        provider_timeout_seconds=0.5,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_cache_redis = FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=fake_cache_redis, settings=settings)

    fake_limiter_redis = FakeAsyncRedisForLimiter()
    limiter_instance = RateLimiter(redis_client=fake_limiter_redis, settings=settings)

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    app.dependency_overrides[get_cache] = lambda: cache_instance
    app.dependency_overrides[get_rate_limiter] = lambda: limiter_instance

    return app, settings, fake_limiter_redis, fake_cache_redis, key_alice, key_bob


def test_rate_limiting_allowed_request_headers(test_db_url: str):
    """Verify successful request within limit returns 200 with X-RateLimit headers."""
    app, settings, _, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=10
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "10"
        assert resp.headers["X-RateLimit-Remaining"] == "9"
        assert int(resp.headers["X-RateLimit-Reset"]) > 0


def test_rate_limiting_boundary_and_429_rejection(test_db_url: str):
    """Verify limit boundary and HTTP 429 response structure with Retry-After and rate limit headers."""
    app, settings, _, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=2, rate_limit_window_seconds=60
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request 1: Allowed (remaining 1)
        r1 = client.post("/v1/chat/completions", json=payload)
        assert r1.status_code == 200
        assert r1.headers["X-RateLimit-Remaining"] == "1"

        # Request 2: Boundary (remaining 0)
        r2 = client.post("/v1/chat/completions", json=payload)
        assert r2.status_code == 200
        assert r2.headers["X-RateLimit-Remaining"] == "0"

        # Request 3: Exceeded -> HTTP 429 Too Many Requests
        r3 = client.post("/v1/chat/completions", json=payload)
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers
        assert int(r3.headers["Retry-After"]) > 0
        assert r3.headers["X-RateLimit-Limit"] == "2"
        assert r3.headers["X-RateLimit-Remaining"] == "0"
        assert "X-RateLimit-Reset" in r3.headers
        assert "X-Request-ID" in r3.headers

        # Verify structured JSON body
        body = r3.json()
        assert "error" in body
        assert body["error"]["code"] == "rate_limit_exceeded"
        assert body["error"]["type"] == "requests"
        assert "Rate limit exceeded" in body["error"]["message"]


def test_rate_limited_request_persisted_to_sqlite(test_db_url: str):
    """Verify rate-limited request is logged with http_status=429 and error_code='rate_limit_exceeded'."""
    app, settings, _, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        r1 = client.post("/v1/chat/completions", json=payload)
        assert r1.status_code == 200

        r2 = client.post("/v1/chat/completions", json=payload)
        assert r2.status_code == 429
        req_id = r2.headers["X-Request-ID"]

    # Verify database record
    engine = get_engine(test_db_url)
    with get_db_session(engine) as session:
        record = session.scalar(select(RequestRecord).where(RequestRecord.request_id == req_id))
        assert record is not None
        assert record.http_status == 429
        assert record.status == "failed"
        assert record.error_code == "rate_limit_exceeded"
        assert record.provider == "gateway"
        assert record.client_id == "alice"

        # Rate limited requests must not generate fake token usage or provider costs
        assert record.usage is not None
        assert record.usage.input_tokens is None
        assert record.usage.output_tokens is None
        assert record.usage.total_tokens is None
        assert record.usage.total_cost is None
        assert record.usage.usage_source == "unavailable"


def test_rate_limited_request_does_not_invoke_provider(test_db_url: str):
    """Verify provider complete() is not invoked when rate limit is exceeded."""
    from app.providers.mock import MockProvider

    app, settings, _, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            r1 = client.post("/v1/chat/completions", json=payload)
            assert r1.status_code == 200
            assert call_count == 1

            r2 = client.post("/v1/chat/completions", json=payload)
            assert r2.status_code == 429
            # Call count remains 1! Provider was never invoked.
            assert call_count == 1


def test_cache_hit_counts_toward_rate_limit_and_does_not_bypass(test_db_url: str):
    """Requirement: Rate limiting is applied before cache lookup. Cache hits consume quota."""
    app, settings, _, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url,
        rate_limit_enabled=True,
        rate_limit_requests=2,
        cache_enabled=True,
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Cache test prompt"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request 1: Cache MISS (consumes quota 1)
        r1 = client.post("/v1/chat/completions", json=payload)
        assert r1.status_code == 200
        assert r1.headers["X-Cache"] == "MISS"
        assert r1.headers["X-RateLimit-Remaining"] == "1"

        # Request 2: Cache HIT (consumes quota 2)
        r2 = client.post("/v1/chat/completions", json=payload)
        assert r2.status_code == 200
        assert r2.headers["X-Cache"] == "HIT"
        assert r2.headers["X-RateLimit-Remaining"] == "0"

        # Request 3: Cache HIT would have occurred, but rate limit is EXCEEDED!
        r3 = client.post("/v1/chat/completions", json=payload)
        assert r3.status_code == 429
        # Does not return cached response
        assert "Rate limit exceeded" in r3.json()["error"]["message"]


def test_client_isolation_and_spoofed_header_prevention(test_db_url: str):
    """Verify Client Alice quota exhaustion does not affect Bob, and forwarded headers cannot spoof identity."""
    app, settings, _, _, key_alice, key_bob = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with TestClient(app) as client:
        # Alice uses her quota
        r_alice_1 = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert r_alice_1.status_code == 200

        # Alice is rate limited on second request, even if she sends spoofed headers
        r_alice_spoof = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {key_alice}",
                "X-Client-ID": "bob",
                "X-Forwarded-For": "10.0.0.99",
            },
        )
        assert r_alice_spoof.status_code == 429

        # Bob's quota remains intact and request succeeds
        r_bob_1 = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key_bob}"},
        )
        assert r_bob_1.status_code == 200
        assert r_bob_1.headers["X-RateLimit-Remaining"] == "0"


def test_auth_failure_does_not_consume_quota(test_db_url: str):
    """Verify invalid API key returns 401 and does not consume client quota."""
    app, settings, fake_limiter_redis, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with TestClient(app) as client:
        # Request with bogus key
        r_bad = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer gw_invalid_key_99999999999999999999"},
        )
        assert r_bad.status_code == 401

        # Limiter should have had 0 calls
        assert fake_limiter_redis.eval_call_count == 0

        # Alice's quota is still 100% available
        r_alice = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert r_alice.status_code == 200
        assert r_alice.headers["X-RateLimit-Remaining"] == "0"


def test_model_validation_failure_does_not_consume_quota(test_db_url: str):
    """Verify schema or model allowlist rejection returns 400 without consuming quota."""
    app, settings, fake_limiter_redis, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    invalid_model_payload = {
        "model": "unauthorized-gpt-5",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        r_bad_model = client.post("/v1/chat/completions", json=invalid_model_payload)
        assert r_bad_model.status_code == 400

        # Limiter was not invoked
        assert fake_limiter_redis.eval_call_count == 0

        # Subsequent valid request passes
        r_valid = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        )
        assert r_valid.status_code == 200


def test_redis_outage_fail_closed_returns_503(test_db_url: str):
    """When Redis is down and policy is fail_closed, return HTTP 503 rate_limiter_unavailable."""
    app, settings, fake_limiter_redis, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url,
        rate_limit_enabled=True,
        rate_limit_failure_policy="fail_closed",
    )

    # Make Redis eval fail
    with patch.object(fake_limiter_redis, "eval", side_effect=ConnectionError("Redis connection lost")):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
            )
            assert resp.status_code == 503
            body = resp.json()
            assert body["error"]["code"] == "rate_limiter_unavailable"
            assert "unavailable" in body["error"]["message"]


def test_redis_outage_fail_open_permits_request(test_db_url: str):
    """When Redis is down and policy is fail_open, request is allowed through to provider."""
    app, settings, fake_limiter_redis, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url,
        rate_limit_enabled=True,
        rate_limit_failure_policy="fail_open",
    )

    with patch.object(fake_limiter_redis, "eval", side_effect=ConnectionError("Redis connection lost")):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
            )
            assert resp.status_code == 200


def test_health_and_readiness_exempt_from_rate_limiting(test_db_url: str):
    """Verify /health and /ready endpoints remain public and are not rate limited."""
    app, settings, fake_limiter_redis, _, _, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    with TestClient(app) as client:
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert "X-RateLimit-Limit" not in r_health.headers

        r_ready = client.get("/ready")
        assert r_ready.status_code == 200
        assert "X-RateLimit-Limit" not in r_ready.headers

        assert fake_limiter_redis.eval_call_count == 0


def test_usage_summary_distinguishes_rate_limited_requests(test_db_url: str):
    """Verify /v1/usage/summary correctly counts rate-limited requests as failed requests."""
    app, settings, _, _, key_alice, _ = build_rate_limit_test_setup(
        test_db_url, rate_limit_enabled=True, rate_limit_requests=1
    )

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request 1: success
        client.post("/v1/chat/completions", json=payload)
        # Request 2: 429 rate limit exceeded
        client.post("/v1/chat/completions", json=payload)

        # Check usage summary
        resp = client.get("/v1/usage/summary")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_requests"] == 2
        assert data["successful_requests"] == 1
        assert data["failed_requests"] == 1
        # Provider count should only attribute the 1 successful call to mock
        assert data["provider_counts"].get("mock") == 1
