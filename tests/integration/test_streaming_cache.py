"""Integration tests for SafeRoute Phase 11C Streaming Cache Replay."""

import json
import sqlite3
import pytest
from starlette.testclient import TestClient
from redis.exceptions import RedisError

from app.api.schemas import ChatCompletionRequest
from app.cache.redis_cache import ExactResponseCache, get_cache, build_cache_key
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET
from tests.unit.test_cache import FakeAsyncRedis


KEY_ALICE = "gw_stream_cache_alice_key_111111111111111111"
KEY_BOB = "gw_stream_cache_bob_key_222222222222222222"


def parse_sse_events(raw_body: str):
    """Parse raw SSE body into a list of parsed JSON event objects or strings."""
    events = []
    lines = raw_body.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("data:"):
            data_content = stripped[len("data:"):].strip()
            if data_content == "[DONE]":
                events.append("[DONE]")
            else:
                try:
                    events.append(json.loads(data_content))
                except Exception:
                    events.append(data_content)
    return events


def build_streaming_cache_test_setup(
    test_db_url: str,
    cache_enabled: bool = True,
    streaming_cache_replay_enabled: bool = True,
    cache_failure_policy: str = "fail_open",
    guardrails_enabled: bool = False,
    guardrails_rules=None,
    fake_redis: FakeAsyncRedis = None,
):
    """Build isolated TestClient with in-memory SQLite and controlled FakeAsyncRedis."""
    reset_db_engine()

    verifier_alice = compute_key_verifier(KEY_ALICE, TEST_AUTH_SECRET)
    verifier_bob = compute_key_verifier(KEY_BOB, TEST_AUTH_SECRET)

    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        database_strict_mode=False,
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[
            {"client_id": "alice", "verifier": verifier_alice, "enabled": True},
            {"client_id": "bob", "verifier": verifier_bob, "enabled": True},
        ],
        allowed_models=[
            "mock-model",
            "mock-timeout",
            "mock-error",
            "mock-short-response",
            "mock-stream-error-after-chunk",
            "llama3.2:1b",
        ],
        default_model="mock-model",
        cache_enabled=cache_enabled,
        streaming_enabled=True,
        streaming_cache_replay_enabled=streaming_cache_replay_enabled,
        cache_failure_policy=cache_failure_policy,
        cache_ttl_seconds=300,
        cache_namespace="v1",
        guardrails_enabled=guardrails_enabled,
        guardrails_rules=guardrails_rules or [],
        metrics_enabled=True,
        provider_timeout_seconds=0.5,
    )

    init_db(get_engine(settings.database_url))

    redis_instance = fake_redis if fake_redis is not None else FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=redis_instance, settings=settings)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: cache_instance

    return app, settings, redis_instance


def test_streaming_cache_miss_populates_then_hit_replays(test_db_url: str):
    """Verify first streaming request misses and populates cache, second request hits and replays SSE."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "stream": True,
        }

        # 1. First streaming request: Must MISS cache, stream from MockProvider, populate cache
        res1 = client.post("/v1/chat/completions", json=payload)
        assert res1.status_code == 200
        assert res1.headers["X-Cache"] == "MISS"
        assert "text/event-stream" in res1.headers["Content-Type"]

        events1 = parse_sse_events(res1.text)
        assert events1[-1] == "[DONE]"
        content_1 = "".join([
            ev["choices"][0]["delta"]["content"]
            for ev in events1[:-1]
            if isinstance(ev, dict) and "content" in ev.get("choices", [{}])[0].get("delta", {})
        ])
        assert len(content_1) > 0
        assert len(fake_redis.store) == 1

        # 2. Second streaming request: Must HIT cache and replay identical text
        res2 = client.post("/v1/chat/completions", json=payload)
        assert res2.status_code == 200
        assert res2.headers["X-Cache"] == "HIT"
        assert res2.headers["X-Cache-Layer"] == "exact"
        assert "text/event-stream" in res2.headers["Content-Type"]

        events2 = parse_sse_events(res2.text)
        assert events2[-1] == "[DONE]"
        content_2 = "".join([
            ev["choices"][0]["delta"]["content"]
            for ev in events2[:-1]
            if isinstance(ev, dict) and "content" in ev.get("choices", [{}])[0].get("delta", {})
        ])
        assert content_2 == content_1

        # Terminal chunk must carry finish_reason and usage
        finish_ev = events2[-2]
        assert finish_ev["choices"][0]["finish_reason"] == "stop"
        assert "usage" in finish_ev

        # Verify SQLite audit records
        db_path = test_db_url.replace("sqlite:///", "")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT request_id, cache_status, stream_status FROM request_records ORDER BY id ASC")
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0][1] == "miss"
        assert rows[0][2] == "completed"
        assert rows[1][1] == "hit"
        assert rows[1][2] == "completed"

        # Check usage_records for usage_source
        req2_id = rows[1][0]
        cur.execute(
            "SELECT u.usage_source FROM usage_records u JOIN request_records r ON u.request_record_id = r.id WHERE r.request_id = ?",
            (req2_id,),
        )
        u_row = cur.fetchone()
        assert u_row is not None
        assert u_row[0] == "cache_hit"
        conn.close()


def test_streaming_cache_cross_replay_non_stream_to_stream(test_db_url: str):
    """Verify response cached via non-streaming request can be replayed as a streaming SSE response."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        base_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Explain relativity in one sentence."}],
        }

        # 1. Non-streaming request populates cache
        res_json = client.post("/v1/chat/completions", json={**base_payload, "stream": False})
        assert res_json.status_code == 200
        assert res_json.headers["X-Cache"] == "MISS"
        json_data = res_json.json()
        expected_text = json_data["choices"][0]["message"]["content"]

        # 2. Streaming request for the identical prompt hits cache and replays as SSE stream
        res_stream = client.post("/v1/chat/completions", json={**base_payload, "stream": True})
        assert res_stream.status_code == 200
        assert res_stream.headers["X-Cache"] == "HIT"
        assert res_stream.headers["X-Cache-Layer"] == "exact"
        assert "text/event-stream" in res_stream.headers["Content-Type"]

        events = parse_sse_events(res_stream.text)
        assert events[-1] == "[DONE]"
        replayed_text = "".join([
            ev["choices"][0]["delta"]["content"]
            for ev in events[:-1]
            if isinstance(ev, dict) and "content" in ev.get("choices", [{}])[0].get("delta", {})
        ])
        assert replayed_text == expected_text


def test_streaming_cache_cross_replay_stream_to_non_stream(test_db_url: str):
    """Verify response cached via streaming request can be returned as a non-streaming JSON response."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        base_payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Count to five."}],
        }

        # 1. Streaming request populates cache
        res_stream = client.post("/v1/chat/completions", json={**base_payload, "stream": True})
        assert res_stream.status_code == 200
        assert res_stream.headers["X-Cache"] == "MISS"
        events = parse_sse_events(res_stream.text)
        stream_text = "".join([
            ev["choices"][0]["delta"]["content"]
            for ev in events[:-1]
            if isinstance(ev, dict) and "content" in ev.get("choices", [{}])[0].get("delta", {})
        ])

        # 2. Non-streaming request for the same prompt hits cache and returns JSON
        res_json = client.post("/v1/chat/completions", json={**base_payload, "stream": False})
        assert res_json.status_code == 200
        assert res_json.headers["X-Cache"] == "HIT"
        assert res_json.headers["X-Cache-Layer"] == "exact"
        json_data = res_json.json()
        assert json_data["choices"][0]["message"]["content"] == stream_text


def test_streaming_cache_incompatible_parameters_miss(test_db_url: str):
    """Verify requests with different temperatures or models produce cache misses."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        # Populate with temp 0.2
        res1 = client.post("/v1/chat/completions", json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test prompt"}],
            "temperature": 0.2,
            "stream": True,
        })
        assert res1.status_code == 200
        assert res1.headers["X-Cache"] == "MISS"

        # Request with temp 0.8 must miss
        res2 = client.post("/v1/chat/completions", json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test prompt"}],
            "temperature": 0.8,
            "stream": True,
        })
        assert res2.status_code == 200
        assert res2.headers["X-Cache"] == "MISS"


def test_streaming_cache_client_isolation(test_db_url: str):
    """Verify Client Alice's cached stream is never served to Client Bob."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Confidential financial prompt"}],
        "stream": True,
    }

    # Alice populates cache
    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client_alice:
        res_alice = client_alice.post("/v1/chat/completions", json=payload)
        assert res_alice.status_code == 200
        assert res_alice.headers["X-Cache"] == "MISS"

    # Bob requests exact same prompt; must MISS cache
    with TestClient(app, headers={"Authorization": f"Bearer {KEY_BOB}"}) as client_bob:
        res_bob = client_bob.post("/v1/chat/completions", json=payload)
        assert res_bob.status_code == 200
        assert res_bob.headers["X-Cache"] == "MISS"


def test_streaming_cache_partial_stream_never_cached(test_db_url: str):
    """Verify mid-stream provider error is never stored in cache."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        # mock-stream-error-after-chunk emits chunk 1 then raises provider error
        res_err = client.post("/v1/chat/completions", json={
            "model": "mock-stream-error-after-chunk",
            "messages": [{"role": "user", "content": "fail midstream"}],
            "stream": True,
        })
        assert res_err.status_code == 200
        events = parse_sse_events(res_err.text)
        assert events[-1] == "[DONE]"
        err_events = [ev for ev in events if isinstance(ev, dict) and "error" in ev]
        assert len(err_events) == 1

        # Cache store must be completely empty!
        assert len(fake_redis.store) == 0


def test_streaming_cache_pre_stream_error_never_cached(test_db_url: str):
    """Verify provider error before stream initialization is never stored in cache."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        res_err = client.post("/v1/chat/completions", json={
            "model": "mock-error",
            "messages": [{"role": "user", "content": "fail prestream"}],
            "stream": True,
        })
        assert res_err.status_code == 502
        assert len(fake_redis.store) == 0


def test_streaming_cache_output_guardrail_block_never_cached(test_db_url: str):
    """Verify streamed responses blocked by output guardrails are never stored in cache."""
    rules = [
        {
            "rule_id": "block-deterministic",
            "name": "Block Deterministic",
            "description": "Block deterministic mock token",
            "direction": "output",
            "detector_type": "keyword",
            "pattern": "deterministic",
            "action": "block",
        }
    ]
    app, settings, fake_redis = build_streaming_cache_test_setup(
        test_db_url,
        guardrails_enabled=True,
        guardrails_rules=rules,
    )

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        res = client.post("/v1/chat/completions", json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        })
        assert res.status_code == 200
        events = parse_sse_events(res.text)
        err_events = [ev for ev in events if isinstance(ev, dict) and "error" in ev]
        assert len(err_events) == 1
        assert err_events[0]["error"]["code"] == "output_guardrail_blocked"

        # Must not be cached!
        assert len(fake_redis.store) == 0


def test_streaming_cache_disabled_setting(test_db_url: str):
    """Verify streaming requests bypass caching when streaming_cache_replay_enabled=False."""
    app, settings, fake_redis = build_streaming_cache_test_setup(
        test_db_url,
        streaming_cache_replay_enabled=False,
    )

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        res = client.post("/v1/chat/completions", json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "disabled test"}],
            "stream": True,
        })
        assert res.status_code == 200
        assert res.headers["X-Cache"] == "BYPASS"
        assert len(fake_redis.store) == 0


class OutageAsyncRedis(FakeAsyncRedis):
    """Fake Redis that throws RedisError on every operation."""

    async def get(self, key: str):
        raise RedisError("Simulated Redis cluster read outage")

    async def set(self, key: str, value: str, ex=None):
        raise RedisError("Simulated Redis cluster write outage")


def test_streaming_cache_redis_failure_fail_open(test_db_url: str):
    """Verify Redis failure in fail_open mode sets X-Cache: ERROR and continues streaming without crashing."""
    outage_redis = OutageAsyncRedis()
    app, settings, _ = build_streaming_cache_test_setup(
        test_db_url,
        fake_redis=outage_redis,
        cache_failure_policy="fail_open",
    )

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        res = client.post("/v1/chat/completions", json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "redis fail test"}],
            "stream": True,
        })
        assert res.status_code == 200
        assert res.headers["X-Cache"] == "ERROR"
        events = parse_sse_events(res.text)
        assert events[-1] == "[DONE]"


def test_streaming_cache_malformed_cache_entry_recovers(test_db_url: str):
    """Verify corrupted cache data is purged and gateway seamlessly falls back to streaming from provider."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "corrupt cache test"}],
        stream=True,
    )
    cache_key = build_cache_key("alice", "mock", req)

    # Inject corrupted payload directly into Redis
    fake_redis.store[cache_key] = json.dumps({"invalid_garbage": True})

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        res = client.post("/v1/chat/completions", json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "corrupt cache test"}],
            "stream": True,
        })
        assert res.status_code == 200
        # Should treat corrupted entry as MISS and fall back to provider
        assert res.headers["X-Cache"] == "MISS"
        events = parse_sse_events(res.text)
        assert events[-1] == "[DONE]"


def test_streaming_cache_metrics_and_zero_token_double_counting(test_db_url: str):
    """Verify Prometheus metrics increment cache hit and do NOT double-count tokens on replay."""
    app, settings, fake_redis = build_streaming_cache_test_setup(test_db_url)

    with TestClient(app, headers={"Authorization": f"Bearer {KEY_ALICE}"}) as client:
        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Metrics double-counting test"}],
            "stream": True,
        }

        from app.metrics import get_metrics
        m = get_metrics()

        # 1. Miss request populates cache
        res1 = client.post("/v1/chat/completions", json=payload)
        assert res1.status_code == 200
        assert res1.headers["X-Cache"] == "MISS"

        # Record metrics right before the hit request
        hits_before = m.cache_operations_total.labels(cache_type="exact", event="hit")._value.get()
        tokens_before = m.tokens_total.labels(type="completion", provider="mock", model="mock-model", source="mock_estimated")._value.get()

        # 2. Hit request replays stream
        res2 = client.post("/v1/chat/completions", json=payload)
        assert res2.status_code == 200
        assert res2.headers["X-Cache"] == "HIT"

        # Check metrics after hit: hit counter must increment by 1.0, tokens must NOT increment
        hits_after = m.cache_operations_total.labels(cache_type="exact", event="hit")._value.get()
        tokens_after = m.tokens_total.labels(type="completion", provider="mock", model="mock-model", source="mock_estimated")._value.get()

        assert hits_after == hits_before + 1.0
        assert tokens_after == tokens_before  # Zero double-counting!
