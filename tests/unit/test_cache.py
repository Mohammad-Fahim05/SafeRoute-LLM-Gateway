"""Unit tests for Redis cache key generation, serialization, TTL, and failure resilience."""

import json
from unittest.mock import AsyncMock, patch
import pytest
from redis.exceptions import ConnectionError, RedisError

from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse, ChatMessage
from app.cache.redis_cache import (
    ExactResponseCache,
    build_cache_key,
    sanitize_redis_url,
)
from app.config import Settings


class FakeAsyncRedis:
    """In-memory async Redis stand-in for deterministic unit testing without a live daemon."""

    def __init__(self) -> None:
        self.store = {}
        self.ttls = {}
        self.deleted_keys = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int = None):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str):
        if key in self.store:
            del self.store[key]
            self.deleted_keys.append(key)
            return 1
        return 0

    async def scan_iter(self, match: str = None, count: int = 100):
        # Simple glob-like prefix matching
        prefix = match.rstrip("*") if match else ""
        for k in list(self.store.keys()):
            if k.startswith(prefix):
                yield k

    async def aclose(self):
        pass

    async def ping(self):
        return True


def test_sanitize_redis_url():
    """Verify credentials in Redis URLs are masked in logs."""
    assert sanitize_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert sanitize_redis_url("redis://:secret123@localhost:6379/0") == "redis://***:***@localhost:6379/0"
    assert sanitize_redis_url("redis://user:pass@10.0.0.1:6379/1") == "redis://***:***@10.0.0.1:6379/1"


def test_cache_key_deterministic_canonical():
    """Requirement 4: Identical canonical requests generate identical keys."""
    req1 = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Hello SafeRoute"}],
        temperature=0.7,
        max_completion_tokens=100,
    )
    req2 = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Hello SafeRoute"}],
        temperature=0.7,
        max_completion_tokens=100,
    )

    key1 = build_cache_key("client_a", "mock", req1, "v1")
    key2 = build_cache_key("client_a", "mock", req2, "v1")
    assert key1 == key2
    assert key1.startswith("saferoute:v1:exact:client_a:")
    assert len(key1.split(":")[-1]) == 64  # SHA-256 hex string


def test_cache_key_different_messages():
    """Requirement 4: Different prompt content produces different cache keys."""
    req1 = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Query 1"}],
    )
    req2 = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Query 2"}],
    )

    assert build_cache_key("client_a", "mock", req1) != build_cache_key("client_a", "mock", req2)


def test_cache_key_message_order_sensitivity():
    """Requirement 4: Changing conversation message order changes the cache key."""
    req1 = ChatCompletionRequest(
        model="mock-model",
        messages=[
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ],
    )
    req2 = ChatCompletionRequest(
        model="mock-model",
        messages=[
            {"role": "assistant", "content": "Answer"},
            {"role": "user", "content": "Question"},
        ],
    )

    assert build_cache_key("client_a", "mock", req1) != build_cache_key("client_a", "mock", req2)


def test_cache_key_client_isolation():
    """Requirement 4: Requests from different clients generate distinct keys for privacy isolation."""
    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "Secret client data"}],
    )

    key_alice = build_cache_key("alice", "mock", req)
    key_bob = build_cache_key("bob", "mock", req)

    assert key_alice != key_bob
    assert "alice" in key_alice
    assert "bob" in key_bob


def test_cache_key_model_and_parameter_sensitivity():
    """Requirement 4: Different models, temperatures, or token limits produce distinct keys."""
    base_req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "test"}],
        temperature=0.5,
        max_completion_tokens=50,
    )
    diff_temp = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "test"}],
        temperature=0.9,
        max_completion_tokens=50,
    )
    diff_tokens = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": "test"}],
        temperature=0.5,
        max_completion_tokens=150,
    )

    key_base = build_cache_key("client_1", "mock", base_req)
    key_temp = build_cache_key("client_1", "mock", diff_temp)
    key_tokens = build_cache_key("client_1", "mock", diff_tokens)

    assert key_base != key_temp
    assert key_base != key_tokens


def test_cache_key_does_not_contain_raw_prompt_or_secrets():
    """Requirement 4: Key must be cryptographically hashed and contain no prompt text."""
    secret_prompt = "CONFIDENTIAL_PASSWORD_12345"
    req = ChatCompletionRequest(
        model="mock-model",
        messages=[{"role": "user", "content": secret_prompt}],
    )
    key = build_cache_key("client_1", "mock", req)

    assert secret_prompt not in key
    assert "CONFIDENTIAL" not in key


import asyncio


def test_cache_set_and_get_lifecycle():
    """Requirement 3 & 10: Storing and retrieving cached responses preserves structure and TTL."""
    async def _test():
        fake_redis = FakeAsyncRedis()
        settings = Settings(cache_enabled=True, cache_ttl_seconds=600)
        cache = ExactResponseCache(redis_client=fake_redis, settings=settings)

        resp = ChatCompletionResponse(
            id="chatcmpl-test1",
            created=1700000000,
            model="mock-model",
            choices=[{
                "index": 0,
                "message": {"role": "assistant", "content": "Cached output"},
                "finish_reason": "stop",
            }],
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "usage_source": "mock_estimated",
                "is_mock_estimate": True,
            },
        )

        # 1. Store
        success = await cache.set("saferoute:v1:exact:test:key1", resp, ttl_seconds=600)
        assert success is True
        assert fake_redis.ttls["saferoute:v1:exact:test:key1"] == 600

        # 2. Retrieve hit
        data, status = await cache.get("saferoute:v1:exact:test:key1")
        assert status == "hit"
        assert data is not None
        assert data["choices"][0]["message"]["content"] == "Cached output"

        # 3. Retrieve miss on unknown key
        miss_data, miss_status = await cache.get("saferoute:v1:exact:test:unknown")
        assert miss_status == "miss"
        assert miss_data is None

    asyncio.run(_test())


def test_cache_corrupted_entry_handled_as_miss():
    """Requirement 8 & 13: Malformed payload in Redis is treated as a miss and purged."""
    async def _test():
        fake_redis = FakeAsyncRedis()
        settings = Settings(cache_enabled=True)
        cache = ExactResponseCache(redis_client=fake_redis, settings=settings)

        # Write corrupt JSON into Redis directly
        fake_redis.store["corrupt_key"] = '{"not_a_valid_response": true}'

        data, status = await cache.get("corrupt_key")
        assert status == "miss"
        assert data is None
        # Verify corrupted key was pruned
        assert "corrupt_key" in fake_redis.deleted_keys

    asyncio.run(_test())


def test_cache_invalidation_methods():
    """Requirement 10: Invalidation by key, client, and namespace."""
    async def _test():
        fake_redis = FakeAsyncRedis()
        settings = Settings(cache_enabled=True, cache_namespace="v1")
        cache = ExactResponseCache(redis_client=fake_redis, settings=settings)

        fake_redis.store["saferoute:v1:exact:client_a:k1"] = "{}"
        fake_redis.store["saferoute:v1:exact:client_a:k2"] = "{}"
        fake_redis.store["saferoute:v1:exact:client_b:k3"] = "{}"

        # Invalidate client_a entries
        deleted = await cache.invalidate_client("client_a")
        assert deleted == 2
        assert "saferoute:v1:exact:client_a:k1" not in fake_redis.store
        assert "saferoute:v1:exact:client_a:k2" not in fake_redis.store
        assert "saferoute:v1:exact:client_b:k3" in fake_redis.store

        # Invalidate entire namespace
        deleted_all = await cache.clear_namespace("v1")
        assert deleted_all == 1
        assert len(fake_redis.store) == 0

    asyncio.run(_test())


def test_cache_fail_open_on_redis_error():
    """Requirement 9: In fail-open mode, Redis exceptions return status='error' without crashing."""
    async def _test():
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("Connection refused")
        mock_redis.set.side_effect = ConnectionError("Connection refused")

        settings = Settings(cache_enabled=True, cache_failure_policy="fail_open")
        cache = ExactResponseCache(redis_client=mock_redis, settings=settings)

        # Read error
        data, status = await cache.get("some_key")
        assert status == "error"
        assert data is None

        # Write error
        resp = ChatCompletionResponse(
            id="c1", created=1, model="m",
            choices=[{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            usage={"usage_source": "unavailable"},
        )
        written = await cache.set("some_key", resp)
        assert written is False

    asyncio.run(_test())


def test_cache_fail_closed_raises_exception():
    """Requirement 9: In fail-closed mode, Redis exceptions raise AppException(500)."""
    from app.core.errors import AppException

    async def _test():
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("Connection refused")

        settings = Settings(cache_enabled=True, cache_failure_policy="fail_closed")
        cache = ExactResponseCache(redis_client=mock_redis, settings=settings)

        with pytest.raises(AppException) as exc_info:
            await cache.get("some_key")

        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code == "cache_error"

    asyncio.run(_test())
