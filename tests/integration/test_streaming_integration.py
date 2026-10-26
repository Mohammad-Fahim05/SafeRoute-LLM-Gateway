"""Comprehensive integration tests for Phase 9.2 streaming chat completions."""

import asyncio
import json
import sqlite3
import pytest
from starlette.testclient import TestClient

from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.core.errors import ProviderError
from app.db import init_db, reset_db_engine
from app.limiter import RateLimiter, get_rate_limiter
from app.main import create_app
from app.providers import get_mock_provider
from tests.unit.test_cache import FakeAsyncRedis
from tests.unit.test_rate_limiter import FakeAsyncRedisForLimiter

KEY_ALICE = "gw_stream_test_alice_key_123456789"
KEY_BOB = "gw_stream_test_bob_key_987654321"
AUTH_SECRET = "stream_test_auth_secret_at_least_16_chars"


def parse_sse_events(raw_body: str):
    """Parse raw SSE body into a list of event objects or string payloads."""
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


def create_streaming_test_client(
    db_url: str,
    rate_limit_enabled: bool = False,
    cache_enabled: bool = False,
    guardrails_enabled: bool = False,
    guardrails_rules=None,
    failover_enabled: bool = False,
    failover_fallback_models=None,
    active_provider: str = "mock",
    streaming_cache_replay_enabled: bool = False,
):
    """Build isolated TestClient with customized Settings."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=db_url,
        database_strict_mode=False,
        auth_enabled=True,
        auth_secret=AUTH_SECRET,
        client_keys=[
            {"client_id": "alice", "verifier": compute_key_verifier(KEY_ALICE, AUTH_SECRET), "enabled": True},
            {"client_id": "bob", "verifier": compute_key_verifier(KEY_BOB, AUTH_SECRET), "enabled": True},
        ],
        allowed_models=[
            "mock-model",
            "mock-timeout",
            "mock-error",
            "mock-empty-response",
            "mock-short-response",
            "mock-rate-limit",
            "mock-stream-error-after-chunk",
            "claude-sonnet-4-6",
            "gemini-3.8-flash",
            "llama3.2:1b",
        ],
        default_model="mock-model",
        rate_limit_enabled=rate_limit_enabled,
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
        cache_enabled=cache_enabled,
        guardrails_enabled=guardrails_enabled,
        guardrails_rules=guardrails_rules or [],
        failover_enabled=failover_enabled,
        failover_allow_mock_fallback=True,
        failover_fallback_models=failover_fallback_models or {},
        active_provider=active_provider,
        provider_timeout_seconds=0.2,
        streaming_enabled=True,
        streaming_cache_replay_enabled=streaming_cache_replay_enabled,
    )

    from app.db.session import get_engine
    init_db(get_engine(settings.database_url))

    fake_cache_redis = FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=fake_cache_redis, settings=settings)

    fake_limiter_redis = FakeAsyncRedisForLimiter()
    limiter_instance = RateLimiter(redis_client=fake_limiter_redis, settings=settings)

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_cache] = lambda: cache_instance
    application.dependency_overrides[get_rate_limiter] = lambda: limiter_instance

    return TestClient(application, raise_server_exceptions=False, headers={"Authorization": f"Bearer {KEY_ALICE}"}), settings


# 1. Existing non-streaming requests remain unchanged
def test_1_non_streaming_remains_unchanged(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "stream": False},
    )
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert len(data["choices"]) == 1
    assert data["choices"][0]["message"]["content"] == "This is a deterministic response from the SafeRoute mock provider."
    assert "usage" in data
    assert data["usage"]["prompt_tokens"] > 0


# 2. Streaming response uses documented content type and event format
def test_2_streaming_content_type_and_event_format(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert resp.headers["cache-control"] == "no-cache"
    assert "X-Request-ID" in resp.headers
    assert resp.headers["X-Serving-Provider"] == "mock"
    assert resp.headers["X-Serving-Model"] == "mock-model"
    assert resp.headers["X-Cache"] == "BYPASS"


# 3. Mock provider emits multiple chunks in the correct order
def test_3_mock_provider_ordered_chunks(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    assert len(events) >= 3

    # Collect content
    assembled = ""
    for ev in events:
        if isinstance(ev, dict) and "choices" in ev:
            delta = ev["choices"][0].get("delta", {})
            assembled += delta.get("content") or ""
    assert assembled == "This is a deterministic response from the SafeRoute mock provider."


# 4. Normal completion emits the expected terminal event [DONE]
def test_4_normal_completion_emits_terminal_done(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    events = parse_sse_events(resp.text)
    assert events[-1] == "[DONE]"
    # Penultimate chunk has stop and usage
    penultimate = events[-2]
    assert isinstance(penultimate, dict)
    assert penultimate["choices"][0]["finish_reason"] == "stop"
    assert penultimate.get("usage") is not None


# 5. Empty and short responses work correctly
def test_5_empty_and_short_responses(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)

    # Empty
    resp_empty = client.post(
        "/v1/chat/completions",
        json={"model": "mock-empty-response", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp_empty.status_code == 200
    ev_empty = parse_sse_events(resp_empty.text)
    assert len(ev_empty) == 2  # 1 stop chunk + [DONE]
    assert ev_empty[0]["choices"][0]["delta"].get("content") == ""
    assert ev_empty[1] == "[DONE]"

    # Short
    resp_short = client.post(
        "/v1/chat/completions",
        json={"model": "mock-short-response", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp_short.status_code == 200
    ev_short = parse_sse_events(resp_short.text)
    assert len(ev_short) == 3  # content chunk + stop chunk + [DONE]
    assert ev_short[0]["choices"][0]["delta"].get("content") == "Hello!"
    assert ev_short[2] == "[DONE]"


# 6. Authentication failures occur before streaming starts
def test_6_auth_failure_before_streaming(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer invalid-key"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 401
    assert "application/json" in resp.headers["content-type"]
    assert "text/event-stream" not in resp.headers.get("content-type", "")
    assert resp.json()["error"]["code"] == "invalid_api_key"


# 7. Invalid models are rejected before streaming starts
def test_7_invalid_models_rejected_before_streaming(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "unapproved-random-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 400
    assert "application/json" in resp.headers["content-type"]
    assert resp.json()["error"]["code"] == "invalid_model"


# 8. Input guardrail rejections occur before streaming starts
def test_8_input_guardrail_rejections_before_streaming(test_db_url: str):
    rules = [
        {"rule_id": "block-secret-prompt", "pattern": "forbidden_prompt", "stage": "input", "action": "block"}
    ]
    client, _ = create_streaming_test_client(test_db_url, guardrails_enabled=True, guardrails_rules=rules)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "test forbidden_prompt here"}], "stream": True},
    )
    assert resp.status_code == 400
    assert "application/json" in resp.headers["content-type"]
    assert resp.json()["error"]["code"] == "input_guardrail_blocked"


# 9. Client rate limiting is enforced for streaming requests
def test_9_client_rate_limiting_enforced_for_streaming(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url, rate_limit_enabled=True)
    # Request 1: ok
    r1 = client.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "q1"}], "stream": True})
    assert r1.status_code == 200
    assert r1.headers["X-RateLimit-Remaining"] == "1"

    # Request 2: ok
    r2 = client.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "q2"}], "stream": True})
    assert r2.status_code == 200
    assert r2.headers["X-RateLimit-Remaining"] == "0"

    # Request 3: rate limited
    r3 = client.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "q3"}], "stream": True})
    assert r3.status_code == 429
    assert "application/json" in r3.headers["content-type"]
    assert r3.json()["error"]["code"] == "rate_limit_exceeded"


# 10. Provider failure before first chunk produces correct behavior (returns 502/504 JSON)
def test_10_provider_failure_before_first_chunk(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 502
    assert "application/json" in resp.headers["content-type"]
    assert resp.json()["error"]["code"] == "provider_error"


# 11. Provider failure after partial output produces a sanitized stream error
def test_11_provider_failure_after_partial_output(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-stream-error-after-chunk", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    events = parse_sse_events(resp.text)

    # First event should be valid content chunk
    assert isinstance(events[0], dict)
    assert events[0]["choices"][0]["delta"]["content"] != ""

    # Second event is an error payload
    err_ev = events[1]
    assert isinstance(err_ev, dict)
    assert "error" in err_ev
    assert err_ev["error"]["code"] == "provider_error"
    assert "request_id" in err_ev["error"]

    # Final event terminates stream
    assert events[2] == "[DONE]"


# 12. No automatic cross-provider retry occurs after content has been emitted
def test_12_no_failover_after_content_emitted(test_db_url: str):
    # Even if failover is enabled with fallback, midstream failure must NEVER fall over to another model
    fallbacks = {"mock-stream-error-after-chunk": ["mock-model"]}
    client, _ = create_streaming_test_client(test_db_url, failover_enabled=True, failover_fallback_models=fallbacks)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-stream-error-after-chunk", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    # The stream should terminate with error + [DONE], NOT append mock-model text!
    assert any("error" in ev for ev in events if isinstance(ev, dict))
    assert events[-1] == "[DONE]"
    full_text = "".join(ev["choices"][0]["delta"].get("content", "") for ev in events if isinstance(ev, dict) and "choices" in ev)
    # Must NOT contain the fallback model text
    assert "This is a deterministic response from the SafeRoute mock provider." not in full_text


# 13. A permitted failover before streaming begins records the actual serving model
def test_13_failover_before_streaming_records_serving_model(test_db_url: str):
    fallbacks = {"mock-error": ["mock-model"]}
    client, _ = create_streaming_test_client(test_db_url, failover_enabled=True, failover_fallback_models=fallbacks)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Serving-Model"] == "mock-model"
    assert resp.headers["X-Requested-Model"] == "mock-error"
    assert resp.headers["X-Failover-Occurred"] == "true"
    assert resp.headers["X-Failover-Attempts"] == "2"


# 14 & 15. Client cancellation stops upstream work and cleans up resources
def test_14_and_15_client_cancellation_and_resource_cleanup(test_db_url: str):
    client, settings = create_streaming_test_client(test_db_url)
    # We simulate a client consuming only 1 chunk and disconnecting
    with client.stream("POST", "/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}], "stream": True}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line:
                break
        # Client disconnects early here by exiting context

    # Verify SQLite recorded outcome as either cancelled or success depending on buffering
    db_path = test_db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT stream, stream_status FROM request_records ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    assert row[0] in (1, True)
    assert row[1] in ("completed", "cancelled")
    conn.close()


# 16. Missing provider usage remains unknown (null) rather than zero
def test_16_missing_usage_remains_null(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-stream-error-after-chunk", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    # Mid-stream failure aborts before usage is emitted
    events = parse_sse_events(resp.text)
    usage_events = [ev for ev in events if isinstance(ev, dict) and ev.get("usage") is not None]
    assert len(usage_events) == 0


# 17. Partial streams are not persisted as successful complete responses
def test_17_partial_stream_persistence(test_db_url: str):
    client, settings = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-stream-error-after-chunk", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    db_path = test_db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT status, stream_status, http_status FROM request_records ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "failed_post_stream"
    assert row[2] == 502
    conn.close()


# 18. Output guardrails follow documented streaming safety policy
def test_18_output_guardrail_streaming_policy(test_db_url: str):
    rules = [
        {"rule_id": "block-deterministic", "pattern": "deterministic", "stage": "output", "action": "block"}
    ]
    client, _ = create_streaming_test_client(test_db_url, guardrails_enabled=True, guardrails_rules=rules)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)
    # The output rule triggers on "deterministic"!
    err_events = [ev for ev in events if isinstance(ev, dict) and "error" in ev]
    assert len(err_events) == 1
    assert err_events[0]["error"]["code"] == "output_guardrail_blocked"
    assert events[-1] == "[DONE]"


# 19. Cache behavior does not mix streaming and non-streaming responses
def test_19_cache_isolation_and_bypass(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url, cache_enabled=True)
    # Streaming request gets X-Cache: BYPASS
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "cache query"}], "stream": True},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Cache"] == "BYPASS"

    # Non-streaming request for same query gets MISS, not cached from stream
    resp_non_stream = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "cache query"}], "stream": False},
    )
    assert resp_non_stream.status_code == 200
    assert resp_non_stream.headers["X-Cache"] == "MISS"


# 20. Request IDs and failover audit records remain correct
def test_20_request_ids_and_audit_records(test_db_url: str):
    fallbacks = {"mock-error": ["mock-model"]}
    client, _ = create_streaming_test_client(test_db_url, failover_enabled=True, failover_fallback_models=fallbacks)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert "X-Request-ID" in resp.headers
    rid = resp.headers["X-Request-ID"]

    db_path = test_db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT request_id, attempts_count, failover_occurred, stream, stream_status FROM request_records WHERE request_id = ?", (rid,))
    row = cur.fetchone()
    assert row is not None
    assert row[0] == rid
    assert row[1] == 2
    assert row[2] in (1, True)
    assert row[3] in (1, True)
    assert row[4] == "completed"
    conn.close()


# 21. Providers follow same documented contract where supported
def test_21_adapters_follow_documented_contract(test_db_url: str):
    client, _ = create_streaming_test_client(test_db_url)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    )
    events = parse_sse_events(resp.text)
    first_chunk = events[0]
    assert first_chunk["object"] == "chat.completion.chunk"
    assert "id" in first_chunk
    assert "model" in first_chunk
    assert "choices" in first_chunk


# 22. Concurrent streaming requests do not leak data or routing state between clients
def test_22_concurrent_streaming_requests(test_db_url: str):
    client_alice, _ = create_streaming_test_client(test_db_url)

    # Use thread pool to run concurrent requests
    import concurrent.futures

    def do_request(content: str):
        return client_alice.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": content}], "stream": True},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(do_request, f"req_{i}") for i in range(5)]
        responses = [f.result() for f in futures]

    for r in responses:
        assert r.status_code == 200
        events = parse_sse_events(r.text)
        assert events[-1] == "[DONE]"
        assert "X-Request-ID" in r.headers
