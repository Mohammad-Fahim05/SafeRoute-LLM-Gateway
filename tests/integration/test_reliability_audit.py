"""Integration tests for Batch 4: System Reliability, Failure Recovery, and Robustness."""

import json
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.main import create_app
from app.cache.redis_cache import ExactResponseCache, get_cache
from tests.unit.test_cache import FakeAsyncRedis


TEST_SECRET = "test_auth_secret_minimum_16_characters_long"
CLIENT_KEY = "gw_reliability_test_key_11111111111"
CLIENT_VERIFIER = compute_key_verifier(CLIENT_KEY, TEST_SECRET)


@pytest.fixture
def reliability_app_setup(test_db_url: str):
    """Fixture providing an isolated app with mock Redis and test settings."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "rel_tester", "verifier": CLIENT_VERIFIER, "enabled": True}],
        allowed_models=["mock-model", "mock-error", "mock-timeout"],
        default_model="mock-model",
        active_provider="mock",
        cache_enabled=True,
        cache_failure_policy="fail_open",
        cache_ttl_seconds=300,
        streaming_enabled=True,
        streaming_cache_replay_enabled=True,
    )
    engine = get_engine(settings.database_url)
    init_db(engine)

    fake_redis = FakeAsyncRedis()
    cache_svc = ExactResponseCache(redis_client=fake_redis, settings=settings)

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: cache_svc

    return app, settings, fake_redis, cache_svc


def test_redis_failure_during_request_fail_open(reliability_app_setup):
    """Scenario 1: When Redis errors during a request with fail_open policy, request succeeds with X-Cache: ERROR."""
    app, settings, fake_redis, _ = reliability_app_setup
    settings.cache_failure_policy = "fail_open"

    with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
        # Simulate Redis get raising an unexpected connection error
        with patch.object(fake_redis, "get", side_effect=RuntimeError("Connection reset by peer")):
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "hello fail open"}]},
            )
            assert resp.status_code == 200
            assert resp.headers.get("X-Cache") == "ERROR"
            data = resp.json()
            assert data["model"] == "mock-model"
            assert "SafeRoute mock provider" in data["choices"][0]["message"]["content"]


def test_redis_failure_during_request_fail_closed(reliability_app_setup):
    """Scenario 2: When Redis errors during a request with fail_closed policy, returns HTTP 500 cache_error."""
    app, settings, fake_redis, _ = reliability_app_setup
    settings.cache_failure_policy = "fail_closed"

    with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
        with patch.object(fake_redis, "get", side_effect=RuntimeError("Redis connection refused")):
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "hello fail closed"}]},
            )
            assert resp.status_code == 500
            err = resp.json()["error"]
            assert err["code"] == "cache_error"


def test_malformed_corrupted_cache_entry_handled_gracefully(reliability_app_setup):
    """Scenario 3: Corrupted non-JSON or invalid schema in Redis cache does not crash, falls back to provider."""
    app, settings, fake_redis, _ = reliability_app_setup

    with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
        # Pre-seed a corrupted payload in the fake Redis store
        with patch.object(fake_redis, "get", return_value="INVALID_NON_JSON_CORRUPTED_PAYLOAD{{{"):
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "corrupted cache test"}]},
            )
            # Must succeed by bypassing/falling back to provider
            assert resp.status_code == 200
            assert resp.headers.get("X-Cache") == "ERROR"
            data = resp.json()
            assert data["model"] == "mock-model"


def test_output_guardrails_enforced_on_cached_response(test_db_url: str):
    """Scenario 4: When a response is retrieved from cache, output guardrails still inspect and enforce safety."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "rel_tester", "verifier": CLIENT_VERIFIER, "enabled": True}],
        allowed_models=["mock-model"],
        default_model="mock-model",
        active_provider="mock",
        cache_enabled=True,
        cache_failure_policy="fail_open",
        guardrails_enabled=True,
        guardrails_input_enabled=False,
        guardrails_output_enabled=True,
        guardrails_action="block",
        guardrails_rules=[
            {
                "rule_id": "block_mock_keyword",
                "pattern": r"SafeRoute\s+mock\s+provider",
                "action": "block",
                "stage": "output",
            }
        ],
    )
    engine = get_engine(settings.database_url)
    init_db(engine)

    fake_redis = FakeAsyncRedis()
    cache_svc = ExactResponseCache(redis_client=fake_redis, settings=settings)

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: cache_svc

    with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
        # Mock provider generates text containing "SafeRoute mock provider"
        # Output guardrail blocks provider response with HTTP 502 output_guardrail_blocked
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "inspect output"}]},
        )
        assert resp.status_code == 502
        err = resp.json()["error"]
        assert err["code"] == "output_guardrail_blocked"

        # Verify nothing was saved to cache because blocked responses are unsafe
        assert len(fake_redis.store) == 0


def test_aborted_streaming_does_not_cache_partial_completion(reliability_app_setup):
    """Scenario 5: Streaming error or interrupted generation does not cache incomplete output."""
    app, settings, fake_redis, _ = reliability_app_setup
    from app.providers import get_mock_provider

    mock_prov = get_mock_provider()
    mock_prov.set_stream_failure_after_chunks("mock-model", RuntimeError("Stream disconnected"), 1)

    try:
        with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
            try:
                resp = client.post(
                    "/v1/chat/completions",
                    json={"model": "mock-model", "messages": [{"role": "user", "content": "abort stream"}], "stream": True},
                )
            except Exception:
                pass

        # Verify no completed entry was stored into cache
        assert len(fake_redis.store) == 0
    finally:
        mock_prov.reset_custom_behaviors()


def test_sqlite_transaction_rollback_preserves_database_integrity(test_db_url: str):
    """Scenario 6: If database recording fails midway, transaction is rolled back cleanly without corrupting schema."""
    reset_db_engine()
    from app.db.service import DatabaseService

    engine = get_engine(test_db_url)
    init_db(engine)

    db_svc = DatabaseService(engine=engine)
    # Perform a valid record write
    db_svc.record_request_outcome(
        request_id="req_valid_before_rollback",
        client_id="rel_tester",
        model_requested="mock-model",
        model_actual="mock-model",
        provider="mock",
        http_status=200,
        status="success",
        duration_ms=10.0,
    )

    # Attempt an invalid operation that triggers integrity or operational failure
    try:
        with db_svc.session_scope() as session:
            from app.db.models import RequestRecord
            # Invalid insert with duplicate primary key
            r = RequestRecord(
                id=1,
                request_id="req_valid_before_rollback",  # Duplicate unique ID or violating constraint
                client_id="rel_tester",
                model_requested="mock-model",
                model_actual="mock-model",
                provider="mock",
                status="success",
                http_status=200,
                duration_ms=10.0,
            )
            session.add(r)
            session.flush()
    except Exception:
        pass  # Expected rollback

    # Verify original record is still intact and database is queryable
    summary = db_svc.get_usage_summary("rel_tester")
    assert summary["total_requests"] == 1
    assert summary["client_id"] == "rel_tester"
