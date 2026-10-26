"""Regression tests for Phase 9.4.1 Independent Semantic Cache Safety Audit.

Verifies:
1. Strict temperature 0.0 determinism (cannot reuse stochastic candidates).
2. Truncated candidates (finish_reason='length') cannot satisfy unconstrained requests.
3. Stale semantic cache entry is actively evicted from Redis on output guardrail failure.
4. Conservative sensitive credential detection (AWS keys, GitHub PATs, JWT, SSN, PAN).
5. Personalized user account records bypass.
6. Non-user final message turns bypass.
7. Length disparity invariance (prevents prefix saturation reuse).
8. Vector dimension mismatch causes safe candidate pruning without crashing.
9. Startup config validation rejects unsupported embedding provider strings.
"""

import asyncio
import json
import time
from typing import Optional
import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.cache.embeddings import DeterministicMockEmbeddingProvider
from app.cache.semantic_cache import (
    SemanticResponseCache,
    is_request_eligible_for_semantic_cache,
)
from app.config import Settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET
from tests.unit.test_semantic_cache import FakeAsyncRedisWithSets


def test_temperature_zero_determinism_strict_isolation(test_db_url: str):
    """Audit 1: temperature 0.0 requests require exact 0.0 match and cannot reuse stochastic outputs."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            semantic_cache_temperature_tolerance=0.15,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req_seed = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Generate cryptographic key derivation function"}],
            temperature=0.12,  # Stochastic, but within 0.15 tolerance of 0.0
        )
        resp_seed = ChatCompletionResponse(
            id="chatcmpl-seed",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "kdf_stochastic()"}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        )
        ok = await cache.set("alice", req_seed, resp_seed, "mock")
        assert ok is True

        # Now incoming request demands strict determinism (temperature: 0.0)
        req_deterministic = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Generate cryptographic key derivation function"}],
            temperature=0.0,
        )
        data, status, sim, reason = await cache.get("alice", req_deterministic, "mock")
        # Must be rejected because 0.0 cannot reuse 0.12!
        assert status == "miss"
        assert reason == "temperature_determinism_mismatch"
        assert data is None

    asyncio.run(_test())


def test_truncated_candidate_cannot_be_reused_for_unconstrained_request(test_db_url: str):
    """Audit 1: Response that stopped due to finish_reason='length' cannot be reused for unconstrained requests."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        # Seed request had max_completion_tokens=20 and stopped due to length
        req_truncated = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Write a complete essay on photosynthesis"}],
            max_completion_tokens=20,
        )
        resp_truncated = ChatCompletionResponse(
            id="chatcmpl-trunc",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Photosynthesis is the process... [truncated]"}, "finish_reason": "length"}],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
        ok = await cache.set("alice", req_truncated, resp_truncated, "mock")
        assert ok is True

        # Incoming probe allows 1000 tokens (or unbounded)
        req_full = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Write a complete essay on photosynthesis"}],
            max_completion_tokens=1000,
        )
        data, status, sim, reason = await cache.get("alice", req_full, "mock")
        assert status == "miss"
        assert reason == "truncated_response_incompatible"
        assert data is None

    asyncio.run(_test())


def test_guardrail_failure_purges_stale_entry_from_redis(test_db_url: str):
    """Audit 2: Stale entry failing output guardrail is actively deleted from Redis store and index."""
    from app.api.routes import get_cache, get_semantic_cache
    from app.cache.redis_cache import ExactResponseCache

    key_alice = "gw_test_alice_key_guardrail_purge_11111"
    verifier_alice = compute_key_verifier(key_alice, TEST_AUTH_SECRET)

    settings = Settings(
        app_env="test",
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "alice", "verifier": verifier_alice, "enabled": True}],
        allowed_models=["mock-model"],
        database_url=test_db_url,
        semantic_cache_enabled=True,
        cache_enabled=False,  # Force Level 2 semantic cache check
        guardrails_enabled=True,
        guardrails_rules=[{
            "rule_id": "block_radioactive",
            "pattern": "radioactive cobalt",
            "match_type": "keyword",
            "stage": "output",
            "action": "block",
        }],
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = FakeAsyncRedisWithSets()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)
    provider = DeterministicMockEmbeddingProvider()
    semantic_cache = SemanticResponseCache(
        redis_client=fake_redis,
        embedding_provider=provider,
        settings=settings,
    )

    from app.config import get_settings

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: exact_cache
    app.dependency_overrides[get_semantic_cache] = lambda: semantic_cache

    # Manually insert a toxic completion into semantic cache before the guardrail rule was active
    req_seed = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "How to dispose of industrial medical isotope sources safely?"}],
    )
    resp_toxic = ChatCompletionResponse(
        id="chatcmpl-toxic",
        object="chat.completion",
        created=int(time.time()),
        model="mock-model",
        choices=[{"index": 0, "message": {"role": "assistant", "content": "Place radioactive cobalt in open trash"}, "finish_reason": "stop"}],
        usage={"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    )
    ok = asyncio.run(semantic_cache.set("alice", req_seed, resp_toxic, "mock"))
    assert ok is True
    assert len(fake_redis.store) == 1

    with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
        # Request with similar prompt
        res = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "How to dispose of industrial medical isotope sources safely?"}],
            },
        )
        # Must be blocked by output guardrail (502)
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "output_guardrail_blocked"

        # AND the stale toxic entry MUST have been purged from Redis!
        assert len(fake_redis.store) == 0


def test_extended_sensitive_patterns_bypass():
    """Audit 2: Verify extended credentials and sensitive PII are rejected by eligibility rules."""
    sensitive_samples = [
        "My AWS credentials: AKIAIOSFODNN7EXAMPLE",
        "Deploy token: ghp_1234567890abcdefghijklmnopqrstuvwxyzAB",
        "API key is sk-1234567890abcdefghijklmnopqrstuvwxyz",
        "Anthropic key sk-ant-api03-1234567890abcdefghijklmnopqrstuvwxyz",
        "Bearer token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisJWTToken",
        "Social security number is 123-45-6789 please record",
        "Card number 4111 2222 3333 4444 for payment",
    ]

    for sample in sensitive_samples:
        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": sample}],
        )
        eligible, reason = is_request_eligible_for_semantic_cache(req)
        assert not eligible, f"Failed to reject sensitive sample: {sample}"
        assert reason == "sensitive_context_bypasses_semantic_cache"


def test_personalized_records_bypass():
    """Audit 2: Verify queries accessing personalized accounts or private records bypass."""
    personalized_queries = [
        "What is my account balance right now?",
        "Show me my order status for yesterday",
        "Please check my medical record history",
        "Update my profile information",
        "Where is my invoice from last month?",
    ]

    for query in personalized_queries:
        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": query}],
        )
        eligible, reason = is_request_eligible_for_semantic_cache(req)
        assert not eligible, f"Failed to reject personalized query: {query}"
        assert reason == "personalized_context_bypasses_semantic_cache" or reason == "temporal_context_bypasses_semantic_cache"


def test_final_non_user_turn_bypasses():
    """Audit 2: Verify conversation ending in assistant prefill or system turn bypasses."""
    # Assistant prefill turn at end
    req_prefill = ChatCompletionRequest(
        model="mock-model",
        messages=[
            {"role": "user", "content": "Format as JSON"},
            {"role": "assistant", "content": "{\n  \"status\":"},
        ],
    )
    eligible, reason = is_request_eligible_for_semantic_cache(req_prefill)
    assert not eligible
    assert reason == "final_message_not_user_turn"


def test_query_length_disparity_invariance(test_db_url: str):
    """Audit 1 & 6: Prompts sharing prefix but differing vastly in length are rejected."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        short_query = "What is Python?"
        long_essay = (
            "What is Python? "
            + "Python is a high-level, general-purpose programming language. " * 15
            + "Explain how Python differs from Assembly language in memory management."
        )

        req_short = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": short_query}],
        )
        resp = ChatCompletionResponse(
            id="chatcmpl-short",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Python is a language."}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        )
        await cache.set("alice", req_short, resp, "mock")

        req_long = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": long_essay}],
        )
        data, status, sim, reason = await cache.get("alice", req_long, "mock")
        # Must NOT reuse short question answer for long detailed query!
        assert status == "miss"
        assert reason == "query_length_disparity" or sim < settings.semantic_cache_threshold

    asyncio.run(_test())


def test_vector_dimension_mismatch_safety(test_db_url: str):
    """Audit 3: Candidate record with corrupted vector dimension is pruned safely without crashing."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider(dimension=384)
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Test vector dimension"}],
        )

        entry_id = "bad_dim_entry"
        entry_key = cache._get_entry_key("alice", entry_id)
        index_key = cache._get_index_key("alice", "mock-model")

        # Corrupted vector: 128 dimensions instead of expected 384
        fake_redis.store[entry_key] = json.dumps({
            "entry_id": entry_id,
            "client_id": "alice",
            "model": "mock-model",
            "provider": "mock",
            "embedding_model": provider.model_name,
            "embedding_version": provider.version,
            "system_instructions": "",
            "history_digest": "none",
            "temperature": 1.0,
            "output_tokens": 10,
            "embedding": [0.1] * 128,  # Mismatched dimension!
            "response": {"choices": [{"message": {"role": "assistant", "content": "answer"}, "finish_reason": "stop"}], "model": "mock-model"},
        })
        await fake_redis.sadd(index_key, entry_id)

        data, status, sim, reason = await cache.get("alice", req, "mock")
        assert status == "miss"
        assert reason == "vector_dimension_mismatch"
        assert data is None

    asyncio.run(_test())


def test_config_validator_rejects_unsupported_embedding_provider():
    """Audit 6: Startup config validation rejects unsupported embedding provider strings."""
    with pytest.raises(ValidationError) as exc:
        Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            semantic_cache_embedding_provider="unsupported_external_provider",
        )
    assert "SEMANTIC_CACHE_EMBEDDING_PROVIDER must be one of" in str(exc.value)


def test_production_environment_forbids_mock_embeddings():
    """Decision 2: Production environment cannot silently or explicitly select mock embeddings."""
    # 1. Config startup validation
    with pytest.raises(ValidationError) as exc:
        Settings(
            app_env="production",
            auth_secret=TEST_AUTH_SECRET,
            semantic_cache_embedding_provider="mock",
        )
    assert "Mock embedding provider 'mock' is strictly forbidden in production" in str(exc.value)

    # 2. Runtime factory safety
    from app.cache.embeddings import get_embedding_provider
    from app.core.errors import AppException

    prod_settings = Settings(
        app_env="production",
        auth_secret=TEST_AUTH_SECRET,
        semantic_cache_embedding_provider="local",  # Valid at config time
    )
    # Manually mutate to simulate unexpected runtime state
    prod_settings.__dict__["semantic_cache_embedding_provider"] = "mock"
    with pytest.raises(AppException) as exc_runtime:
        get_embedding_provider(prod_settings)
    assert exc_runtime.value.error_code == "configuration_error"


def test_personalized_query_bypasses_reads_and_writes_end_to_end(test_db_url: str):
    """Decision 1: Personalized requests bypass both cache reads and cache writes end-to-end."""
    from app.api.routes import get_cache, get_semantic_cache
    from app.cache.redis_cache import ExactResponseCache
    from app.config import get_settings
    from app.providers.mock import MockProvider

    key_alice = "gw_test_alice_key_personalized_11111"
    verifier_alice = compute_key_verifier(key_alice, TEST_AUTH_SECRET)

    settings = Settings(
        app_env="test",
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "alice", "verifier": verifier_alice, "enabled": True}],
        allowed_models=["mock-model"],
        database_url=test_db_url,
        cache_enabled=False,
        semantic_cache_enabled=True,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = FakeAsyncRedisWithSets()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)
    semantic_cache = SemanticResponseCache(
        redis_client=fake_redis,
        embedding_provider=DeterministicMockEmbeddingProvider(),
        settings=settings,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: exact_cache
    app.dependency_overrides[get_semantic_cache] = lambda: semantic_cache

    provider_calls = 0
    orig_complete = MockProvider.complete

    async def counting_complete(self, req):
        nonlocal provider_calls
        provider_calls += 1
        return await orig_complete(self, req)

    from unittest.mock import patch

    with patch.object(MockProvider, "complete", counting_complete):
        with TestClient(app, headers={"Authorization": f"Bearer {key_alice}"}) as client:
            personalized_payload = {
                "model": "mock-model",
                "messages": [{"role": "user", "content": "Can you check my order status for yesterday?"}],
            }

            # First request: Proceeds to provider, but MUST NOT be inserted into Redis semantic cache
            res1 = client.post("/v1/chat/completions", json=personalized_payload)
            assert res1.status_code == 200
            assert provider_calls == 1
            # Verify Redis cache has 0 entries (write was bypassed!)
            assert len(fake_redis.store) == 0

            # Second identical request: Must NOT hit cache (read is bypassed!), must call provider again
            res2 = client.post("/v1/chat/completions", json=personalized_payload)
            assert res2.status_code == 200
            assert provider_calls == 2
            # Still 0 entries in Redis
            assert len(fake_redis.store) == 0


def test_adversarial_polarity_negation_inversion_rejected(test_db_url: str):
    """Audit 5: Adversarial near-match with negation polarity inversion is rejected."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req_positive = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            temperature=0.0,
        )
        resp_positive = ChatCompletionResponse(
            id="chatcmpl-pos",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Paris"}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8},
        )
        ok = await cache.set("alice", req_positive, resp_positive, "mock")
        assert ok is True

        req_negative = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "What is not the capital of France?"}],
            temperature=0.0,
        )
        data, status, sim, reason = await cache.get("alice", req_negative, "mock")
        assert status == "miss"
        assert reason == "polarity_inversion_mismatch"
        assert data is None

    asyncio.run(_test())


def test_adversarial_numeric_entity_mismatch_rejected(test_db_url: str):
    """Audit 5: Adversarial near-match differing only by numbers is rejected."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req_2plus2 = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Calculate 2 + 2"}],
            temperature=0.0,
        )
        resp_4 = ChatCompletionResponse(
            id="chatcmpl-4",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "4"}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        )
        ok = await cache.set("alice", req_2plus2, resp_4, "mock")
        assert ok is True

        req_2plus3 = ChatCompletionRequest(
            model="mock-model",
            messages=[{"role": "user", "content": "Calculate 2 + 3"}],
            temperature=0.0,
        )
        data, status, sim, reason = await cache.get("alice", req_2plus3, "mock")
        assert status == "miss"
        assert reason == "numeric_entity_mismatch"
        assert data is None

    asyncio.run(_test())


def test_adversarial_system_instruction_disparity_rejected(test_db_url: str):
    """Audit 4: Matching user query with different system instructions is rejected."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req_tutor = ChatCompletionRequest(
            model="mock-model",
            messages=[
                {"role": "system", "content": "You are a serious academic tutor."},
                {"role": "user", "content": "Explain relativity."},
            ],
            temperature=0.0,
        )
        resp = ChatCompletionResponse(
            id="chatcmpl-tutor",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Formal academic explanation."}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        ok = await cache.set("alice", req_tutor, resp, "mock")
        assert ok is True

        req_comedian = ChatCompletionRequest(
            model="mock-model",
            messages=[
                {"role": "system", "content": "You are a standup comedian."},
                {"role": "user", "content": "Explain relativity."},
            ],
            temperature=0.0,
        )
        data, status, sim, reason = await cache.get("alice", req_comedian, "mock")
        assert status == "miss"
        assert reason == "system_instructions_mismatch"
        assert data is None

    asyncio.run(_test())


def test_adversarial_conversation_history_digest_mismatch_rejected(test_db_url: str):
    """Audit 4: Identical latest query in different multi-turn conversation contexts is rejected."""
    async def _test():
        fake_redis = FakeAsyncRedisWithSets()
        settings = Settings(
            app_env="test",
            auth_secret=TEST_AUTH_SECRET,
            database_url=test_db_url,
            semantic_cache_enabled=True,
            cache_namespace="v1",
        )
        provider = DeterministicMockEmbeddingProvider()
        cache = SemanticResponseCache(
            redis_client=fake_redis,
            embedding_provider=provider,
            settings=settings,
        )

        req_ctx1 = ChatCompletionRequest(
            model="mock-model",
            messages=[
                {"role": "user", "content": "I am traveling to Tokyo."},
                {"role": "assistant", "content": "Have a wonderful trip to Tokyo!"},
                {"role": "user", "content": "What is the best airport?"},
            ],
            temperature=0.0,
        )
        resp = ChatCompletionResponse(
            id="chatcmpl-tokyo",
            object="chat.completion",
            created=int(time.time()),
            model="mock-model",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "Haneda or Narita airport."}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        )
        ok = await cache.set("alice", req_ctx1, resp, "mock")
        assert ok is True

        req_ctx2 = ChatCompletionRequest(
            model="mock-model",
            messages=[
                {"role": "user", "content": "I am traveling to London."},
                {"role": "assistant", "content": "Enjoy London!"},
                {"role": "user", "content": "What is the best airport?"},
            ],
            temperature=0.0,
        )
        data, status, sim, reason = await cache.get("alice", req_ctx2, "mock")
        assert status == "miss"
        assert reason == "conversation_history_mismatch"
        assert data is None

    asyncio.run(_test())
