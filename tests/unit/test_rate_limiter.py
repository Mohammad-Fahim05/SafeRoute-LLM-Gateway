"""Unit tests for Redis-backed rate limiter logic, atomic Lua script, client isolation, and failure modes."""

import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from redis.exceptions import ConnectionError, RedisError

from app.config import Settings
from app.core.errors import RateLimiterUnavailableError
from app.limiter.redis_limiter import (
    LUA_FIXED_WINDOW_RATE_LIMIT,
    RateLimiter,
    RateLimitResult,
    build_rate_limit_key,
)


class FakeAsyncRedisForLimiter:
    """In-memory async Redis stand-in simulating atomic Lua script evaluation."""

    def __init__(self) -> None:
        self.counters = {}  # key -> int count
        self.ttls = {}      # key -> int ttl seconds
        self.deleted_keys = []
        self.eval_call_count = 0

    async def eval(self, script: str, numkeys: int, *keys_and_args):
        self.eval_call_count += 1
        key = str(keys_and_args[0])
        window_seconds = int(keys_and_args[1])

        current = self.counters.get(key, 0) + 1
        self.counters[key] = current

        if current == 1:
            self.ttls[key] = window_seconds

        ttl = self.ttls.get(key, window_seconds)
        return [current, ttl]

    async def delete(self, *keys: str):
        count = 0
        for k in keys:
            if k in self.counters:
                del self.counters[k]
                self.ttls.pop(k, None)
                count += 1
                self.deleted_keys.append(k)
        return count

    async def aclose(self):
        pass

    async def ping(self):
        return True


def test_build_rate_limit_key_deterministic():
    """Verify rate limit key format is deterministic and isolates clients and namespaces."""
    key1 = build_rate_limit_key("client-alice", "v1")
    key2 = build_rate_limit_key("client-alice", "v1")
    key3 = build_rate_limit_key("client-bob", "v1")
    key4 = build_rate_limit_key("client-alice", "v2")

    assert key1 == "saferoute:v1:ratelimit:client-alice"
    assert key1 == key2
    assert key1 != key3, "Clients must have distinct keys"
    assert key1 != key4, "Different namespaces must not collide"


def test_disabled_rate_limiter_permits_all():
    """When RATE_LIMIT_ENABLED is False, limiter returns allowed=True with status='disabled'."""
    async def _test():
        settings = Settings(rate_limit_enabled=False)
        limiter = RateLimiter(settings=settings)

        result = await limiter.check_rate_limit("client-alice")
        assert result.allowed is True
        assert result.status == "disabled"
        assert result.remaining == settings.rate_limit_requests

    asyncio.run(_test())


def test_basic_rate_limiting_boundary_and_rejection():
    """Verify requests up to limit pass, and the N+1 request is rejected with correct retry_after."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_requests=3,
            rate_limit_window_seconds=60,
        )
        fake_redis = FakeAsyncRedisForLimiter()
        limiter = RateLimiter(settings=settings, redis_client=fake_redis)

        # Request 1: allowed, remaining=2
        res1 = await limiter.check_rate_limit("client-alice")
        assert res1.allowed is True
        assert res1.remaining == 2
        assert res1.limit == 3
        assert res1.status == "ok"

        # Request 2: allowed, remaining=1
        res2 = await limiter.check_rate_limit("client-alice")
        assert res2.allowed is True
        assert res2.remaining == 1
        assert res2.status == "ok"

        # Request 3 (boundary): allowed, remaining=0
        res3 = await limiter.check_rate_limit("client-alice")
        assert res3.allowed is True
        assert res3.remaining == 0
        assert res3.status == "ok"

        # Request 4 (exceeded): rejected
        res4 = await limiter.check_rate_limit("client-alice")
        assert res4.allowed is False
        assert res4.remaining == 0
        assert res4.status == "exceeded"
        assert res4.retry_after == 60

    asyncio.run(_test())


def test_client_isolation():
    """Verify Client Alice exceeding quota does not consume or affect Client Bob's quota."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_requests=2,
            rate_limit_window_seconds=60,
        )
        fake_redis = FakeAsyncRedisForLimiter()
        limiter = RateLimiter(settings=settings, redis_client=fake_redis)

        # Exhaust Alice's quota
        await limiter.check_rate_limit("client-alice")
        await limiter.check_rate_limit("client-alice")
        res_alice_3 = await limiter.check_rate_limit("client-alice")
        assert res_alice_3.allowed is False

        # Bob should have a full, untouched quota
        res_bob_1 = await limiter.check_rate_limit("client-bob")
        assert res_bob_1.allowed is True
        assert res_bob_1.remaining == 1

        res_bob_2 = await limiter.check_rate_limit("client-bob")
        assert res_bob_2.allowed is True
        assert res_bob_2.remaining == 0

    asyncio.run(_test())


def test_per_client_rate_limit_override():
    """Verify per-client limits override gateway defaults when configured."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_requests=100,
            rate_limit_window_seconds=60,
            client_keys=[
                {
                    "client_id": "custom-client",
                    "rate_limit_requests": 2,
                    "rate_limit_window_seconds": 30,
                }
            ],
        )
        fake_redis = FakeAsyncRedisForLimiter()
        limiter = RateLimiter(settings=settings, redis_client=fake_redis)

        # Custom client has limit 2
        r1 = await limiter.check_rate_limit("custom-client")
        assert r1.allowed is True
        assert r1.limit == 2

        r2 = await limiter.check_rate_limit("custom-client")
        assert r2.allowed is True
        assert r2.remaining == 0

        r3 = await limiter.check_rate_limit("custom-client")
        assert r3.allowed is False
        assert r3.retry_after == 30

        # Default client still gets 100
        r_default = await limiter.check_rate_limit("standard-client")
        assert r_default.allowed is True
        assert r_default.limit == 100

    asyncio.run(_test())


def test_ttl_not_reset_on_subsequent_requests():
    """Verify that subsequent requests within the window do not reset TTL back to initial value."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_requests=5,
            rate_limit_window_seconds=60,
        )
        fake_redis = FakeAsyncRedisForLimiter()
        limiter = RateLimiter(settings=settings, redis_client=fake_redis)

        # First request sets initial TTL = 60
        await limiter.check_rate_limit("client-alice")
        key = build_rate_limit_key("client-alice", settings.rate_limit_namespace)
        assert fake_redis.ttls[key] == 60

        # Simulate 15 seconds elapsed
        fake_redis.ttls[key] = 45

        # Second request
        res2 = await limiter.check_rate_limit("client-alice")
        assert res2.allowed is True
        # The Lua script returns remaining TTL; it should NOT reset to 60!
        assert res2.reset_seconds == 45

    asyncio.run(_test())


def test_reset_client_clears_rate_limit():
    """Verify reset_client deletes client counter in Redis."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_requests=1,
            rate_limit_window_seconds=60,
        )
        fake_redis = FakeAsyncRedisForLimiter()
        limiter = RateLimiter(settings=settings, redis_client=fake_redis)

        await limiter.check_rate_limit("client-alice")
        res_blocked = await limiter.check_rate_limit("client-alice")
        assert res_blocked.allowed is False

        # Reset
        reset_ok = await limiter.reset_client("client-alice")
        assert reset_ok is True

        # After reset, client is allowed again
        res_after_reset = await limiter.check_rate_limit("client-alice")
        assert res_after_reset.allowed is True

    asyncio.run(_test())


def test_shared_state_across_multiple_limiter_instances():
    """Verify multiple limiter instances (e.g. gateway workers) share same Redis state."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_requests=2,
            rate_limit_window_seconds=60,
        )
        shared_redis = FakeAsyncRedisForLimiter()
        worker_1 = RateLimiter(settings=settings, redis_client=shared_redis)
        worker_2 = RateLimiter(settings=settings, redis_client=shared_redis)

        # Worker 1 consumes 1
        r1 = await worker_1.check_rate_limit("client-alice")
        assert r1.allowed is True
        assert r1.remaining == 1

        # Worker 2 consumes 2
        r2 = await worker_2.check_rate_limit("client-alice")
        assert r2.allowed is True
        assert r2.remaining == 0

        # Worker 1 is now rejected because shared state is at limit
        r3 = await worker_1.check_rate_limit("client-alice")
        assert r3.allowed is False

    asyncio.run(_test())


def test_redis_failure_fail_closed_raises_503():
    """In fail_closed mode, Redis connection failure raises RateLimiterUnavailableError."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_failure_policy="fail_closed",
        )
        failing_redis = AsyncMock()
        failing_redis.eval.side_effect = ConnectionError("Connection refused")
        limiter = RateLimiter(settings=settings, redis_client=failing_redis)

        with pytest.raises(RateLimiterUnavailableError) as exc_info:
            await limiter.check_rate_limit("client-alice")
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == "rate_limiter_unavailable"

    asyncio.run(_test())


def test_redis_failure_fail_open_permits_request():
    """In fail_open mode, Redis connection failure allows request with status='error'."""
    async def _test():
        settings = Settings(
            rate_limit_enabled=True,
            rate_limit_failure_policy="fail_open",
        )
        failing_redis = AsyncMock()
        failing_redis.eval.side_effect = ConnectionError("Connection refused")
        limiter = RateLimiter(settings=settings, redis_client=failing_redis)

        res = await limiter.check_rate_limit("client-alice")
        assert res.allowed is True
        assert res.status == "error"

    asyncio.run(_test())


def test_redis_none_client_fail_closed_vs_fail_open():
    """When _get_client returns None (Redis completely unavailable on startup)."""
    async def _test():
        settings_closed = Settings(rate_limit_enabled=True, rate_limit_failure_policy="fail_closed")
        limiter_closed = RateLimiter(settings=settings_closed)
        with patch.object(limiter_closed, "_get_client", return_value=None):
            with pytest.raises(RateLimiterUnavailableError):
                await limiter_closed.check_rate_limit("client-alice")

        settings_open = Settings(rate_limit_enabled=True, rate_limit_failure_policy="fail_open")
        limiter_open = RateLimiter(settings=settings_open)
        with patch.object(limiter_open, "_get_client", return_value=None):
            res = await limiter_open.check_rate_limit("client-alice")
            assert res.allowed is True
            assert res.status == "error"

    asyncio.run(_test())
