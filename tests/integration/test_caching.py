"""Integration tests for Redis exact-match response caching, client isolation, and usage accounting."""

import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select

from app.api.schemas import ChatCompletionResponse
from app.cache.redis_cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import get_db_session, init_db, reset_db_engine
from app.db.models import RequestRecord, UsageRecord
from app.db.session import get_engine
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET, VALID_KEY_VERIFIER, VALID_TEST_KEY
from tests.unit.test_cache import FakeAsyncRedis


def build_test_setup(
    test_db_url: str,
    cache_enabled: bool = True,
    cache_failure_policy: str = "fail_open",
    streaming_cache_replay_enabled: bool = False,
):
    """Helper to initialize test environment with in-memory SQLite and FakeAsyncRedis."""
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
        database_url=test_db_url,
        cache_enabled=cache_enabled,
        cache_ttl_seconds=300,
        cache_namespace="v1",
        cache_failure_policy=cache_failure_policy,
        provider_timeout_seconds=0.5,
        streaming_cache_replay_enabled=streaming_cache_replay_enabled,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=fake_redis, settings=settings)

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    app.dependency_overrides[get_cache] = lambda: cache_instance

    return app, settings, fake_redis, key_alice, key_bob


def test_cache_miss_then_hit_flow(test_db_url: str):
    """Requirements 2, 7, 8, 11: 1st request misses and caches, 2nd hits without calling provider."""
    from app.providers.mock import MockProvider

    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        req_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Explain gravity in one sentence"}],
            "temperature": 0.5,
        }

        call_count = 0
        orig_complete = MockProvider.complete

        async def counting_complete(self, req):
            nonlocal call_count
            call_count += 1
            return await orig_complete(self, req)

        with patch.object(MockProvider, "complete", counting_complete):
            # 1. First Request: Must MISS cache, invoke provider, and return X-Cache: MISS
            res1 = client.post("/v1/chat/completions", json=req_payload)
            assert res1.status_code == 200
            assert res1.headers.get("X-Cache") == "MISS"
            assert call_count == 1
            rid1 = res1.headers["X-Request-ID"]
            data1 = res1.json()
            assert data1["choices"][0]["message"]["content"] is not None

            # Verify it was stored in Redis
            assert len(fake_redis.store) == 1

            # 2. Second Request (Identical): Must HIT cache, NOT invoke provider, return X-Cache: HIT
            res2 = client.post("/v1/chat/completions", json=req_payload)
            assert res2.status_code == 200
            assert res2.headers.get("X-Cache") == "HIT"
            # Provider invocation count must NOT increase!
            assert call_count == 1

            rid2 = res2.headers["X-Request-ID"]
            data2 = res2.json()

            # Requirement 7: Request IDs must be unique per incoming request!
            assert rid1 != rid2
            assert data2["id"] == f"chatcmpl-{rid2}"
            # Completion content matches
            assert data2["choices"][0]["message"]["content"] == data1["choices"][0]["message"]["content"]

        # 3. Verify SQLite Records
        with get_db_session() as session:
            rec1 = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid1))
            assert rec1 is not None
            assert rec1.cache_status == "miss"
            assert rec1.provider_latency_ms is not None
            assert rec1.usage.usage_source == "mock_estimated"

            rec2 = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid2))
            assert rec2 is not None
            assert rec2.cache_status == "hit"
            # Requirement 7 & 11: Provider latency is None on cache hit, cost is 0.0, usage_source is cache_hit
            assert rec2.provider_latency_ms is None
            assert rec2.usage.usage_source == "cache_hit"
            assert rec2.usage.total_cost == 0.0
            assert rec2.usage.calculation_status == "cache_hit"


def test_cache_client_isolation(test_db_url: str):
    """Requirement 4 & 7: Alice's cached response is never served to Bob."""
    app, settings, fake_redis, key_alice, key_bob = build_test_setup(test_db_url)

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Confidential financial report"}],
    }

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client_alice, \
         TestClient(app, headers={"Authorization": f"Bearer {key_bob}"}) as client_bob:

        # Alice requests and populates cache
        res_alice = client_alice.post("/v1/chat/completions", json=payload)
        assert res_alice.status_code == 200
        assert res_alice.headers.get("X-Cache") == "MISS"

        # Bob sends the exact same request
        res_bob = client_bob.post("/v1/chat/completions", json=payload)
        assert res_bob.status_code == 200
        # Bob must get a MISS because cache keys are isolated by client_id
        assert res_bob.headers.get("X-Cache") == "MISS"

        # Now both Alice and Bob have their own isolated cache entries
        assert len(fake_redis.store) == 2


def test_cache_miss_on_parameter_change(test_db_url: str):
    """Requirement 4: Changing model or temperature misses cache."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        base_req = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Calculate orbital velocity"}],
            "temperature": 0.2,
        }
        res1 = client.post("/v1/chat/completions", json=base_req)
        assert res1.status_code == 200
        assert res1.headers.get("X-Cache") == "MISS"

        # Change temperature
        res_temp = client.post("/v1/chat/completions", json={**base_req, "temperature": 0.8})
        assert res_temp.status_code == 200
        assert res_temp.headers.get("X-Cache") == "MISS"

        # Change messages
        res_msg = client.post("/v1/chat/completions", json={**base_req, "messages": [{"role": "user", "content": "Calculate escape velocity"}]})
        assert res_msg.status_code == 200
        assert res_msg.headers.get("X-Cache") == "MISS"


def test_cache_disabled_behavior(test_db_url: str):
    """Requirement 3 & 6: When cache_enabled=False, returns DISABLED and bypasses Redis."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url, cache_enabled=False)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        req = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Hello cache disabled"}],
        }
        res = client.post("/v1/chat/completions", json=req)
        assert res.status_code == 200
        assert res.headers.get("X-Cache") == "DISABLED"
        assert len(fake_redis.store) == 0

        # DB record reflects disabled cache status
        rid = res.headers["X-Request-ID"]
        with get_db_session() as session:
            rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
            assert rec.cache_status == "disabled"


def test_provider_errors_are_never_cached(test_db_url: str):
    """Requirement 6 & 8: Provider 504 timeouts and 502 outages are not stored in cache."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Trigger mock provider error
        res_error = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Trigger error"}]},
        )
        assert res_error.status_code == 502
        assert len(fake_redis.store) == 0

        # Trigger mock provider timeout
        res_timeout = client.post(
            "/v1/chat/completions",
            json={"model": "mock-timeout", "messages": [{"role": "user", "content": "Trigger timeout"}]},
        )
        assert res_timeout.status_code == 504
        assert len(fake_redis.store) == 0


def test_redis_outage_fail_open_behavior(test_db_url: str):
    """Requirement 9: Redis read/write outage in fail_open mode falls back to provider with X-Cache: ERROR."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url, cache_failure_policy="fail_open")

    # Force redis client to throw ConnectionError
    failing_redis = AsyncMock()
    failing_redis.get.side_effect = ConnectionError("Redis server connection reset")
    failing_redis.set.side_effect = ConnectionError("Redis server connection reset")

    failing_cache = ExactResponseCache(redis_client=failing_redis, settings=settings)
    app.dependency_overrides[get_cache] = lambda: failing_cache

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        res = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Test Redis outage"}]},
        )
        # Request succeeds via provider fallback!
        assert res.status_code == 200
        assert res.headers.get("X-Cache") == "ERROR"
        data = res.json()
        assert data["choices"][0]["message"]["content"] is not None

        rid = res.headers["X-Request-ID"]
        with get_db_session() as session:
            rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
            assert rec.cache_status == "error"
            assert rec.status == "success"


def test_usage_summary_accounting_with_cache_hits(test_db_url: str):
    """Requirement 7, 11, 12: Cache hit does not increment provider call counts or fabricate cloud token spend."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        req = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Consistent question"}],
        }

        # Request 1 (MISS)
        client.post("/v1/chat/completions", json=req)
        # Request 2 (HIT)
        client.post("/v1/chat/completions", json=req)
        # Request 3 (HIT)
        client.post("/v1/chat/completions", json=req)

        summary_res = client.get("/v1/usage/summary")
        assert summary_res.status_code == 200
        summary = summary_res.json()

        assert summary["client_id"] == "alice"
        assert summary["total_requests"] == 3
        assert summary["successful_requests"] == 3
        assert summary["cache_hits"] == 2
        assert summary["cache_misses"] == 1

        # CRITICAL: Provider was only invoked 1 time! Cache hits must NOT increment upstream provider count!
        assert summary["provider_counts"]["mock"] == 1


def test_streaming_requests_bypass_cache(test_db_url: str):
    """Requirement 6: Streaming requests are not cacheable and return X-Cache: BYPASS."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        res = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "stream query"}], "stream": True},
        )
        assert res.status_code == 200
        assert res.headers["X-Cache"] == "BYPASS"
        assert "text/event-stream" in res.headers["content-type"]
        assert len(fake_redis.store) == 0


def test_ineligible_and_auth_failures_bypass_cache(test_db_url: str):
    """Requirement 5 & 6: Authentication and validation failures do not access or populate cache."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    # 1. Unauthenticated request (401)
    with TestClient(app) as client_unauth:
        res = client_unauth.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert res.status_code == 401
        assert len(fake_redis.store) == 0

    # 2. Invalid model (400)
    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        res = client.post(
            "/v1/chat/completions",
            json={"model": "unapproved-model", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert res.status_code == 400
        assert len(fake_redis.store) == 0

        # 3. Exceeds max_completion_tokens (422)
        res_limit = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "max_completion_tokens": 999999},
        )
        assert res_limit.status_code == 422
        assert len(fake_redis.store) == 0


def test_csv_export_contains_cache_status(test_db_url: str):
    """Requirement 11: Exported CSV includes cache_status column and values."""
    app, settings, fake_redis, key_alice, _ = build_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        req = {"model": "mock-model", "messages": [{"role": "user", "content": "csv query"}]}
        client.post("/v1/chat/completions", json=req)
        client.post("/v1/chat/completions", json=req)

        export_res = client.get("/v1/usage/export")
        assert export_res.status_code == 200
        csv_text = export_res.text

        # Verify header and row values
        assert "cache_status" in csv_text
        assert "miss" in csv_text
        assert "hit" in csv_text
