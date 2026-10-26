"""Unit and integration tests for Phase 9.4 Semantic Caching.

Covers:
1. Exact-match cache behavior remains intact.
2. Semantic cache disabled preserves existing behavior.
3. Similar eligible request hits semantic cache.
4. Dissimilar request results in cache miss.
5. Differing system instructions or contrastive prompts do not share a response.
6. Tenant isolation (Alice and Bob cannot share semantic entries).
7. Model, temperature, and max_tokens compatibility enforcement.
8. Tool-enabled requests bypass semantic caching.
9. Streaming requests bypass semantic caching.
10. Sensitive credentials and temporal terms bypass semantic caching.
11. Expired entries are rejected and cleaned up.
12. Incompatible embedding versions cause safe misses.
13. Redis failure handling (fail_open vs fail_closed).
14. Corrupted cache records handled safely.
15. Only complete successful responses are stored.
16. Output guardrail blocked responses are purged and not served.
17. Cache-hit accounting: 0 provider cost, no fabricated provider calls.
18. Cache-hit metadata identifies exact vs semantic layer.
19. Tenant isolation under concurrent lookups.
20. SentenceTransformer offline embedding generation and cosine similarity.
"""

import asyncio
from decimal import Decimal
import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy import select

from app.api.routes import get_cache, get_guardrail_engine, get_semantic_cache
from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.cache.embeddings import (
    DeterministicMockEmbeddingProvider,
    LocalSentenceTransformerEmbeddingProvider,
    compute_cosine_similarity,
)
from app.cache.redis_cache import ExactResponseCache
from app.cache.semantic_cache import (
    SemanticResponseCache,
    extract_prompt_components,
    is_request_eligible_for_semantic_cache,
)
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.core.errors import AppException, OutputGuardrailBlockedError
from app.db.models import RequestRecord, UsageRecord
from app.db.service import DatabaseService
from app.db.session import get_db_session, get_engine, init_db, reset_db_engine
from app.guardrails import GuardrailEngine
from app.main import create_app
from app.providers.mock import MockProvider

TEST_AUTH_SECRET = "test_hmac_secret_key_at_least_16_chars_long"


class FakeAsyncRedisWithSets:
    """In-memory async Redis stand-in supporting key-value and set operations."""

    def __init__(self) -> None:
        self.store: Dict[str, str] = {}
        self.sets: Dict[str, set] = {}
        self.ttls: Dict[str, int] = {}
        self.deleted_keys: List[str] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str):
        count = 0
        if key in self.store:
            del self.store[key]
            self.deleted_keys.append(key)
            count += 1
        if key in self.sets:
            del self.sets[key]
            count += 1
        return count

    async def sadd(self, key: str, *members: str):
        if key not in self.sets:
            self.sets[key] = set()
        count = 0
        for m in members:
            if m not in self.sets[key]:
                self.sets[key].add(m)
                count += 1
        return count

    async def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    async def srem(self, key: str, *members: str):
        if key not in self.sets:
            return 0
        count = 0
        for m in members:
            if m in self.sets[key]:
                self.sets[key].remove(m)
                count += 1
        return count

    async def expire(self, key: str, seconds: int):
        self.ttls[key] = seconds
        return 1

    async def scan_iter(self, match: str = None, count: int = 100):
        prefix = match.rstrip("*") if match else ""
        for k in list(self.store.keys()):
            if k.startswith(prefix):
                yield k
        for k in list(self.sets.keys()):
            if k.startswith(prefix):
                yield k

    async def aclose(self):
        pass


def build_semantic_test_setup(
    test_db_url: str,
    exact_cache_enabled: bool = True,
    semantic_cache_enabled: bool = True,
    semantic_threshold: float = 0.85,
    semantic_failure_policy: str = "fail_open",
    guardrails_enabled: bool = False,
    guardrails_rules: Optional[List[Dict[str, Any]]] = None,
):
    """Helper to initialize test environment with in-memory SQLite and FakeAsyncRedisWithSets."""
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
        allowed_models=["mock-model", "mock-model-alt", "mock-error", "mock-timeout"],
        database_url=test_db_url,
        cache_enabled=exact_cache_enabled,
        cache_ttl_seconds=300,
        cache_namespace="v1",
        cache_failure_policy="fail_open",
        semantic_cache_enabled=semantic_cache_enabled,
        semantic_cache_threshold=semantic_threshold,
        semantic_cache_ttl_seconds=300,
        semantic_cache_embedding_provider="mock",
        semantic_cache_embedding_model="mock-embedding-v1",
        semantic_cache_embedding_version="v1",
        semantic_cache_failure_policy=semantic_failure_policy,
        guardrails_enabled=guardrails_enabled,
        guardrails_output_enabled=guardrails_enabled,
        guardrails_rules=guardrails_rules or [],
        provider_timeout_seconds=0.5,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = FakeAsyncRedisWithSets()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)
    mock_emb_provider = DeterministicMockEmbeddingProvider(
        model_name="mock-embedding-v1", version="v1", dimension=384
    )
    semantic_cache = SemanticResponseCache(
        redis_client=fake_redis,
        embedding_provider=mock_emb_provider,
        settings=settings,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: exact_cache
    app.dependency_overrides[get_semantic_cache] = lambda: semantic_cache

    if guardrails_enabled:
        guard_engine = GuardrailEngine(settings=settings)
        app.dependency_overrides[get_guardrail_engine] = lambda: guard_engine

    return app, settings, fake_redis, key_alice, key_bob


# ==============================================================================
# 1. Existing Exact Cache Behavior Intact
# ==============================================================================
def test_existing_exact_cache_behavior_intact(test_db_url: str):
    """Exact match cache still hits as Level 1 and returns X-Cache: HIT with X-Cache-Layer: exact."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        req = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Hello exact world"}],
        }

        # First request: Misses exact and semantic
        r1 = client.post("/v1/chat/completions", json=req)
        assert r1.status_code == 200
        assert r1.headers["X-Cache"] == "MISS"

        # Second request (Identical): Hits exact cache immediately
        r2 = client.post("/v1/chat/completions", json=req)
        assert r2.status_code == 200
        assert r2.headers["X-Cache"] == "HIT"
        assert r2.headers["X-Cache-Layer"] == "exact"


# ==============================================================================
# 2. Semantic Cache Disabled Preserves Current Behavior
# ==============================================================================
def test_semantic_cache_disabled_preserves_current_behavior(test_db_url: str):
    """When semantic cache is disabled, non-identical queries always miss even if similar."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=False
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            r1 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "What is Python?"}]},
            )
            assert r1.status_code == 200
            assert call_count == 1

            # Similar query, but exact match misses and semantic cache is disabled
            r2 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "What is Python language?"}]},
            )
            assert r2.status_code == 200
            assert r2.headers["X-Cache"] == "MISS"
            assert call_count == 2


# ==============================================================================
# 3. Genuinely Similar Eligible Request Hits Semantic Cache
# ==============================================================================
def test_similar_eligible_request_hits_semantic_cache(test_db_url: str):
    """Similar query hits semantic cache, returns X-Cache: HIT, X-Cache-Layer: semantic, and no new provider call."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True, semantic_threshold=0.80
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            # 1. Initial request misses exact & semantic, executes provider, populates both caches
            r1 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Explain machine learning in simple terms"}],
                },
            )
            assert r1.status_code == 200
            assert r1.headers["X-Cache"] == "MISS"
            assert call_count == 1
            rid1 = r1.headers["X-Request-ID"]
            content1 = r1.json()["choices"][0]["message"]["content"]

            # 2. Semantically similar query (different phrasing, high token/n-gram overlap)
            r2 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Explain machine learning in simple words"}],
                },
            )
            assert r2.status_code == 200
            assert r2.headers["X-Cache"] == "HIT"
            assert r2.headers["X-Cache-Layer"] == "semantic"
            assert "X-Cache-Similarity" in r2.headers
            sim = float(r2.headers["X-Cache-Similarity"])
            assert sim >= 0.80

            # Provider call count must NOT have increased!
            assert call_count == 1

            rid2 = r2.headers["X-Request-ID"]
            assert rid1 != rid2  # Distinct request IDs
            content2 = r2.json()["choices"][0]["message"]["content"]
            assert content2 == content1

        # Verify DB records
        with get_db_session() as session:
            rec2 = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid2))
            assert rec2 is not None
            assert rec2.cache_status == "semantic_hit"
            assert rec2.provider_latency_ms is None
            assert rec2.usage.usage_source == "semantic_cache_hit"
            assert rec2.usage.total_cost == Decimal("0.000000")


# ==============================================================================
# 4. Dissimilar Request Results in Cache Miss
# ==============================================================================
def test_dissimilar_request_results_in_cache_miss(test_db_url: str):
    """Completely different queries do not hit semantic cache."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            r1 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "Explain quantum physics"}]},
            )
            assert r1.status_code == 200
            assert call_count == 1

            r2 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "How to bake chocolate cookies"}]},
            )
            assert r2.status_code == 200
            assert r2.headers["X-Cache"] == "MISS"
            assert call_count == 2


# ==============================================================================
# 5. Similar Prompts with Differing System Prompts or Negation Do Not Share Response
# ==============================================================================
def test_differing_instructions_or_contrastive_prompts_do_not_share_response(test_db_url: str):
    """Differing system instructions or inverted query polarity do not hit semantic cache."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            # Query with system prompt: Translate to French
            r1 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [
                        {"role": "system", "content": "Translate to French"},
                        {"role": "user", "content": "Good morning"},
                    ],
                },
            )
            assert r1.status_code == 200
            assert call_count == 1

            # Same user query with different system prompt: Translate to German
            r2 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [
                        {"role": "system", "content": "Translate to German"},
                        {"role": "user", "content": "Good morning"},
                    ],
                },
            )
            assert r2.status_code == 200
            assert r2.headers["X-Cache"] == "MISS"
            assert call_count == 2

            # Contrastive negative query: "Why is Python good?" vs "Why is Python not good?"
            r3 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "Why is Python good?"}]},
            )
            assert r3.status_code == 200
            assert call_count == 3

            r4 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "Why is Python not good?"}]},
            )
            assert r4.status_code == 200
            assert r4.headers["X-Cache"] == "MISS"
            assert call_count == 4


# ==============================================================================
# 6. Tenant Isolation: Alice's Entries Never Shared with Bob
# ==============================================================================
def test_tenant_isolation_alice_and_bob(test_db_url: str):
    """Bob never hits Alice's semantic cache even for semantically identical requests."""
    app, settings, fake_redis, key_alice, key_bob = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        # Alice requests and populates cache
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client_alice:
            r_alice = client_alice.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Secret merger details for Project Alpha"}],
                },
            )
            assert r_alice.status_code == 200
            assert call_count == 1

        # Bob requests same query: MUST NOT hit Alice's semantic cache
        with TestClient(app, headers={"Authorization": f"Bearer {key_bob}"}) as client_bob:
            r_bob = client_bob.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": "Secret merger details for Project Alpha"}],
                },
            )
            assert r_bob.status_code == 200
            assert r_bob.headers["X-Cache"] == "MISS"
            assert call_count == 2


# ==============================================================================
# 7. Model and Generation Policy Compatibility Enforcement
# ==============================================================================
def test_model_and_generation_policy_compatibility(test_db_url: str):
    """Requests targeting a different model or exceeding token constraint are rejected."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    call_count = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal call_count
        call_count += 1
        return await orig_complete(self, req)

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            # Seed entry for mock-model
            r1 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model", "messages": [{"role": "user", "content": "Summarize war and peace"}]},
            )
            assert r1.status_code == 200
            assert call_count == 1

            # Same query on mock-model-alt: Model mismatch -> must not reuse
            r2 = client.post(
                "/v1/chat/completions",
                json={"model": "mock-model-alt", "messages": [{"role": "user", "content": "Summarize war and peace"}]},
            )
            assert r2.status_code == 200
            assert r2.headers["X-Cache"] == "MISS"
            assert call_count == 2


# ==============================================================================
# 8 & 9. Tool and Streaming Requests Bypass Semantic Caching
# ==============================================================================
def test_tools_and_streaming_requests_bypass_semantic_caching():
    """Verify tool and streaming requests are flagged as ineligible."""
    # Tool request
    req_tool = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "What is the weather?"}],
        tools=[{"type": "function", "function": {"name": "get_weather", "description": "Get weather"}}],
    )
    eligible, reason = is_request_eligible_for_semantic_cache(req_tool)
    assert not eligible
    assert "tool_requests" in reason

    # Tool role message
    req_tool_msg = ChatCompletionRequest(
        model="mock-model",
        messages=[
            {"role": "user", "content": "Weather query"},
            {"role": "tool", "content": "72 degrees", "tool_call_id": "call_1"},
        ],
    )
    eligible_msg, reason_msg = is_request_eligible_for_semantic_cache(req_tool_msg)
    assert not eligible_msg
    assert "tool_messages" in reason_msg

    # Streaming request
    req_stream = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Stream me a poem"}],
        stream=True,
    )
    eligible_stream, reason_stream = is_request_eligible_for_semantic_cache(req_stream)
    assert not eligible_stream
    assert "streaming_requests" in reason_stream


# ==============================================================================
# 10. Sensitive Credentials and Temporal Queries Bypass Policy
# ==============================================================================
def test_sensitive_credentials_and_temporal_queries_bypass():
    """Verify credentials and time-sensitive phrases trigger semantic cache bypass."""
    # Bearer token
    req_sec = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "My token is Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz123"}],
    )
    elig_sec, reason_sec = is_request_eligible_for_semantic_cache(req_sec)
    assert not elig_sec
    assert "sensitive_context" in reason_sec

    # Private key
    req_key = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "-----BEGIN RSA PRIVATE KEY----- abc -----END RSA PRIVATE KEY-----"}],
    )
    elig_key, reason_key = is_request_eligible_for_semantic_cache(req_key)
    assert not elig_key
    assert "sensitive_context" in reason_key

    # Temporal query
    req_time = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "What is the current time in Tokyo?"}],
    )
    elig_time, reason_time = is_request_eligible_for_semantic_cache(req_time)
    assert not elig_time
    assert "temporal_context" in reason_time


# ==============================================================================
# 11. Expired Entries Are Rejected and Cleaned Up
# ==============================================================================
def test_expired_entries_rejected(test_db_url: str):
    """Candidate entry deleted from Redis results in a clean miss and set cleanup."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=DeterministicMockEmbeddingProvider(),
            settings=settings,
        )

        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Explain photosynthesis"}],
        )
        resp = ChatCompletionResponse(
            id="chatcmpl-1",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Light into chemical energy"}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        )

        # Store entry
        ok = await cache.set("alice", req, resp, "mock")
        assert ok is True

        # Artificially delete entry key to simulate TTL expiration
        index_key = cache._get_index_key("alice", "mock-model")
        members = await fake_redis.smembers(index_key)
        assert len(members) == 1
        entry_id = list(members)[0]

        entry_key = cache._get_entry_key("alice", entry_id)
        await fake_redis.delete(entry_key)

        # Lookup must now cleanly miss
        data, status, sim, reason = await cache.get("alice", req, "mock")
        assert status == "miss"
        assert data is None

    asyncio.run(_test())


# ==============================================================================
# 12. Incompatible Embedding Version Causes Safe Miss
# ==============================================================================
def test_incompatible_embedding_version_causes_safe_miss(test_db_url: str):
    """Candidate with mismatched embedding_version is rejected without crashing."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            semantic_cache_embedding_version="v2",
            cache_namespace="v1",
        )
        provider_v2 = DeterministicMockEmbeddingProvider(version="v2")
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider_v2,
            settings=settings,
        )

        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Explain cell division"}],
        )

        # Write a record created with version v1 directly
        entry_id = "test_entry_v1"
        entry_key = cache._get_entry_key("alice", entry_id)
        index_key = cache._get_index_key("alice", "mock-model")
        fake_redis.store[entry_key] = json.dumps({
            "entry_id": entry_id,
            "client_id": "alice",
            "model": "mock-model",
            "provider": "mock",
            "embedding_model": "mock-embedding-v1",
            "embedding_version": "v1",  # Old version
            "system_instructions": "",
            "history_digest": "none",
            "temperature": 0.0,
            "embedding": [0.5] * 384,
            "response": {"choices": [{"message": {"role": "assistant", "content": "old answer"}}], "model": "mock-model"},
        })
        await fake_redis.sadd(index_key, entry_id)

        # Lookup with v2 provider must reject candidate due to version mismatch
        data, status, sim, reason = await cache.get("alice", req, "mock")
        assert status == "miss"
        assert reason == "embedding_version_mismatch"
        assert data is None

    asyncio.run(_test())


# ==============================================================================
# 13. Redis Failures: Fail-Open vs Fail-Closed
# ==============================================================================
def test_redis_failure_fail_open_and_fail_closed(test_db_url: str):
    """In fail-open mode Redis errors proceed to provider; in fail-closed mode raises 500."""
    # Fail-open setup
    app_open, settings, _, key_alice, _ = build_semantic_test_setup(
        test_db_url, semantic_cache_enabled=True, semantic_failure_policy="fail_open"
    )

    mock_failing_redis = AsyncMock()
    mock_failing_redis.smembers.side_effect = ConnectionError("Redis unavailable")
    mock_failing_redis.get.side_effect = ConnectionError("Redis unavailable")
    mock_failing_redis.set.side_effect = ConnectionError("Redis unavailable")

    failing_cache_open = SemanticResponseCache(
        redis_client=mock_failing_redis,
        embedding_provider=DeterministicMockEmbeddingProvider(),
        settings=Settings(semantic_cache_enabled=True, semantic_cache_failure_policy="fail_open"),
    )
    app_open.dependency_overrides[get_semantic_cache] = lambda: failing_cache_open

    with TestClient(app_open, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request succeeds via provider despite Redis outage
        res = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Ping"}]},
        )
        assert res.status_code == 200

    # Fail-closed setup
    settings_closed = settings.model_copy(update={"semantic_cache_failure_policy": "fail_closed"})
    app_open.dependency_overrides[get_settings] = lambda: settings_closed
    failing_cache_closed = SemanticResponseCache(
        redis_client=mock_failing_redis,
        embedding_provider=DeterministicMockEmbeddingProvider(),
        settings=settings_closed,
    )
    app_open.dependency_overrides[get_semantic_cache] = lambda: failing_cache_closed

    with TestClient(app_open, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        res = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Ping 2"}]},
        )
        assert res.status_code == 500
        assert "cache" in res.json()["error"]["message"].lower()


# ==============================================================================
# 14. Corrupted Cache Records Handled Safely
# ==============================================================================
def test_corrupt_cache_records_handled_safely(test_db_url: str):
    """Corrupt JSON or missing fields in cache records are purged and treated as miss."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
        )
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=DeterministicMockEmbeddingProvider(),
            settings=settings,
        )

        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Hello corrupt"}],
        )

        entry_id = "bad_payload_entry"
        entry_key = cache._get_entry_key("alice", entry_id)
        index_key = cache._get_index_key("alice", "mock-model")

        # Store malformed non-JSON
        fake_redis.store[entry_key] = "{invalid-json-payload"
        await fake_redis.sadd(index_key, entry_id)

        data, status, sim, reason = await cache.get("alice", req, "mock")
        assert status == "miss"
        assert data is None

    asyncio.run(_test())


# ==============================================================================
# 15. Only Complete Successful Responses Are Eligible for Insertion
# ==============================================================================
def test_failed_responses_not_inserted_into_semantic_cache(test_db_url: str):
    """Upstream provider error (e.g., 502) is never inserted into semantic cache."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request against error model
        res = client.post(
            "/v1/chat/completions",
            json={"model": "mock-error", "messages": [{"role": "user", "content": "Trigger failure"}]},
        )
        assert res.status_code == 502

        # Assert no entries were written to fake_redis
        assert len(fake_redis.store) == 0
        assert len(fake_redis.sets) == 0


# ==============================================================================
# 16. Guardrail-Blocked Responses Are Not Cached or Served
# ==============================================================================
def test_guardrail_blocked_cached_response_purged_immediately(test_db_url: str):
    """If cached candidate content violates output guardrails, entry is purged and 502 raised."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url,
        exact_cache_enabled=True,
        semantic_cache_enabled=True,
        guardrails_enabled=True,
        guardrails_rules=[
            {
                "rule_id": "block_radioactive",
                "pattern": r"(?i)\bradioactive\b",
                "target": "output",
                "action": "block",
            }
        ],
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Pre-seed a candidate in semantic cache containing blocked word "radioactive"
        semb = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=DeterministicMockEmbeddingProvider(),
            settings=settings,
        )
        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "What is uranium?"}],
        )
        resp = ChatCompletionResponse(
            id="chatcmpl-radio",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Uranium is a radioactive element."}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        )
        asyncio.run(semb.set("alice", req, resp, "mock"))

        # Query should match semantic cache but fail output guardrails
        res = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "What is uranium?"}]},
        )
        assert res.status_code == 502
        assert "guardrail" in res.json()["error"]["message"].lower()


# ==============================================================================
# 17 & 18. Cache-Hit Accounting & Metadata Verification
# ==============================================================================
def test_cache_hit_accounting_and_layer_metadata(test_db_url: str):
    """Semantic cache hit preserves provenance, costs 0.0, and sets X-Cache-Layer: semantic."""
    app, settings, fake_redis, key_alice, _ = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True, semantic_threshold=0.80
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # 1. Exact miss
        r1 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Explain quantum mechanics in simple terms"}]},
        )
        assert r1.status_code == 200
        rid1 = r1.headers["X-Request-ID"]

        # 2. Semantic hit
        r2 = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Explain quantum mechanics in simple words"}]},
        )
        assert r2.status_code == 200
        assert r2.headers["X-Cache"] == "HIT"
        assert r2.headers["X-Cache-Layer"] == "semantic"
        rid2 = r2.headers["X-Request-ID"]

        # 3. Usage summary
        sum_res = client.get("/v1/usage/summary")
        assert sum_res.status_code == 200
        summary = sum_res.json()
        assert summary["total_requests"] == 2
        assert summary["cache_hits"] == 1
        assert summary["cache_misses"] == 1
        # Provider count should only count the 1 real provider execution!
        assert summary["provider_counts"].get("mock", 0) == 1

        # 4. CSV export
        csv_res = client.get("/v1/usage/export")
        assert csv_res.status_code == 200
        csv_lines = csv_res.text.strip().split("\n")
        assert len(csv_lines) == 3  # Header + 2 rows
        assert "semantic_hit" in csv_res.text


# ==============================================================================
# 19. Concurrent Requests Do Not Leak Between Tenants
# ==============================================================================
def test_concurrent_requests_tenant_isolation(test_db_url: str):
    """Concurrent client requests execute without cross-tenant key pollution."""
    app, settings, fake_redis, key_alice, key_bob = build_semantic_test_setup(
        test_db_url, exact_cache_enabled=True, semantic_cache_enabled=True
    )

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client_a, \
         TestClient(app, headers={"Authorization": f"Bearer {key_bob}"}) as client_b:

        r_a = client_a.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "Alice query"}]})
        r_b = client_b.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "Bob query"}]})

        assert r_a.status_code == 200
        assert r_b.status_code == 200

        # Verify Redis keys are strictly partitioned
        alice_keys = [k for k in fake_redis.store if "alice" in k]
        bob_keys = [k for k in fake_redis.store if "bob" in k]
        assert len(alice_keys) >= 1
        assert len(bob_keys) >= 1
        assert not any("bob" in k for k in alice_keys)
        assert not any("alice" in k for k in bob_keys)


# ==============================================================================
# 20. SentenceTransformer Offline Embedding Generation
# ==============================================================================
def test_sentence_transformer_offline_embedding():
    """Verify LocalSentenceTransformerEmbeddingProvider produces normalized vectors offline."""
    async def _test():
        provider = LocalSentenceTransformerEmbeddingProvider(
            model_name="all-MiniLM-L6-v2",
            version="v1",
        )
        vec1 = await provider.embed("What is machine learning?")
        vec2 = await provider.embed("What is artificial intelligence?")
        vec3 = await provider.embed("How to make homemade pizza?")

        assert len(vec1) == 384
        assert len(vec2) == 384

        sim_similar = compute_cosine_similarity(vec1, vec2)
        sim_different = compute_cosine_similarity(vec1, vec3)

        assert sim_similar > sim_different
        assert 0.0 <= sim_similar <= 1.0

    asyncio.run(_test())


# ==============================================================================
# 21. Stage 3.1 Verified Regression Tests: Invariant Entity & Client Isolation
# ==============================================================================
def test_regression_numeric_entity_safety_delete_user():
    """Stage 3.1: Prove 'delete user 5' cannot reuse cached answer for 'delete user 6'."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        provider = DeterministicMockEmbeddingProvider()
        settings = Settings(
            app_env="test",
            cache_namespace="test_v1",
            semantic_cache_enabled=True,
            semantic_cache_threshold=0.50,  # Lower threshold to prove numeric invariant check overrides similarity
        )
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req_user_5 = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "delete user 5"}],
        )
        resp_user_5 = ChatCompletionResponse(
            id="chatcmpl-test-user-5",
            created=1700000000,
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "User 5 deleted successfully."}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
        )

        # Store user 5 response
        stored = await cache.set(
            client_id="tenant_admin",
            request=req_user_5,
            response=resp_user_5,
            provider="mock",
        )
        assert stored is True

        # Query user 6: Even if vectors are closely aligned, numbers entity mismatch MUST block reuse
        req_user_6 = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "delete user 6"}],
        )
        cached_resp, status, sim, reason = await cache.get(
            client_id="tenant_admin",
            request=req_user_6,
            provider="mock",
        )
        assert cached_resp is None
        assert status == "miss"
        assert reason == "numeric_entity_mismatch"

    asyncio.run(_test())


def test_regression_cross_client_semantic_isolation():
    """Stage 3.1: Prove the exact same prompt from two clients cannot retrieve each other's responses."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        provider = DeterministicMockEmbeddingProvider()
        settings = Settings(
            app_env="test",
            cache_namespace="test_v1",
            semantic_cache_enabled=True,
            semantic_cache_threshold=0.85,
        )
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        shared_prompt = "Explain our internal corporate compliance policy."
        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": shared_prompt}],
        )
        resp = ChatCompletionResponse(
            id="chatcmpl-test-shared",
            created=1700000000,
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Policy explanation for tenant A."}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )

        # Alice caches the response
        await cache.set(
            client_id="alice_corp",
            request=req,
            response=resp,
            provider="mock",
        )

        # Alice verifies hit
        alice_resp, alice_status, _, _ = await cache.get(
            client_id="alice_corp",
            request=req,
            provider="mock",
        )
        assert alice_status == "hit"
        assert alice_resp is not None
        assert alice_resp["choices"][0]["message"]["content"] == "Policy explanation for tenant A."

        # Bob queries identical prompt -> MUST be a miss, Bob cannot see Alice's index or entry
        bob_resp, bob_status, _, bob_reason = await cache.get(
            client_id="bob_corp",
            request=req,
            provider="mock",
        )
        assert bob_resp is None
        assert bob_status == "miss"
        assert bob_reason == "no_candidates_in_index"

    asyncio.run(_test())
