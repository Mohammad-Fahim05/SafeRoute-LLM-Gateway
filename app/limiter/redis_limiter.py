"""Redis-backed client rate limiter for SafeRoute LLM Gateway."""

from dataclasses import dataclass
from typing import Any, Optional, Tuple
from fastapi import Depends
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from app.cache.redis_cache import sanitize_redis_url
from app.config import Settings, get_settings
from app.core.errors import RateLimiterUnavailableError
from app.core.logging import logger

_limiter_redis_client: Optional[Redis] = None

# Lua script to atomically increment and set expiration on the first hit.
# Guarantees zero race condition between INCR and EXPIRE across concurrent workers.
# Preserves TTL on subsequent calls without resetting window expiration.
LUA_FIXED_WINDOW_RATE_LIMIT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call('TTL', KEYS[1])
if ttl == -1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
    ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""


@dataclass
class RateLimitResult:
    """Holds rate limit evaluation output and header metrics."""

    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after: int = 0
    status: str = "ok"  # "ok", "exceeded", "disabled", "error"


def build_rate_limit_key(client_id: str, namespace: str = "v1") -> str:
    """Construct an isolated rate-limit key for an authenticated client.

    Key Pattern: saferoute:{namespace}:ratelimit:{client_id}
    Does not contain raw prompt, completion, API keys, or secrets.
    """
    return f"saferoute:{namespace}:ratelimit:{client_id}"


class RateLimiter:
    """Manages Redis connection and executes atomic rate-limiting checks."""

    def __init__(
        self,
        redis_client: Optional[Redis] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = redis_client

    async def _get_client(self) -> Optional[Redis]:
        """Obtain or lazily initialize the shared Redis async client."""
        if self._client is not None:
            return self._client

        if not self.settings.rate_limit_enabled:
            return None

        global _limiter_redis_client
        if _limiter_redis_client is None:
            try:
                _limiter_redis_client = from_url(
                    self.settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                )
            except Exception as exc:
                clean_url = sanitize_redis_url(self.settings.redis_url)
                logger.warning(f"Failed to initialize rate limiter Redis client for {clean_url}: {exc}")
                if self.settings.rate_limit_failure_policy == "fail_closed":
                    raise RateLimiterUnavailableError()
                return None

        self._client = _limiter_redis_client
        return self._client

    async def check_rate_limit(self, client_id: str) -> RateLimitResult:
        """Evaluate rate limit quota for the given authenticated client.

        Returns RateLimitResult containing allow decision, limit, remaining, and TTL.
        Raises RateLimiterUnavailableError in fail_closed mode if Redis is down.
        """
        limit, window = self.settings.get_client_rate_limits(client_id)

        if not self.settings.rate_limit_enabled:
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_seconds=0,
                retry_after=0,
                status="disabled",
            )

        key = build_rate_limit_key(client_id, self.settings.rate_limit_namespace)

        try:
            client = await self._get_client()
            if client is None:
                # Could not connect to Redis
                if self.settings.rate_limit_failure_policy == "fail_closed":
                    raise RateLimiterUnavailableError()
                return RateLimitResult(
                    allowed=True,
                    limit=limit,
                    remaining=limit,
                    reset_seconds=0,
                    retry_after=0,
                    status="error",
                )

            # Execute atomic Lua script
            eval_res = await client.eval(
                LUA_FIXED_WINDOW_RATE_LIMIT,
                1,
                key,
                str(window),
            )

            current = int(eval_res[0])
            ttl = int(eval_res[1])
            reset_seconds = max(1, ttl)

            allowed = current <= limit
            remaining = max(0, limit - current)
            retry_after = reset_seconds if not allowed else 0

            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=remaining,
                reset_seconds=reset_seconds,
                retry_after=retry_after,
                status="ok" if allowed else "exceeded",
            )

        except RateLimiterUnavailableError:
            raise
        except RedisError as exc:
            clean_url = sanitize_redis_url(self.settings.redis_url)
            logger.warning(f"Rate limiter Redis error on {clean_url}: {type(exc).__name__}")
            if self.settings.rate_limit_failure_policy == "fail_closed":
                raise RateLimiterUnavailableError()
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_seconds=0,
                retry_after=0,
                status="error",
            )
        except Exception as exc:
            logger.warning(f"Unexpected rate limiter error: {exc}")
            if self.settings.rate_limit_failure_policy == "fail_closed":
                raise RateLimiterUnavailableError()
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit,
                reset_seconds=0,
                retry_after=0,
                status="error",
            )

    async def reset_client(self, client_id: str) -> bool:
        """Reset rate limit counter for a client (useful in tests and admin actions)."""
        key = build_rate_limit_key(client_id, self.settings.rate_limit_namespace)
        try:
            client = await self._get_client()
            if client is None:
                return False
            return bool(await client.delete(key))
        except Exception as exc:
            logger.warning(f"Failed to reset client rate limit: {exc}")
            return False

    async def aclose(self) -> None:
        """Close Redis connection."""
        global _limiter_redis_client
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        if _limiter_redis_client is not None:
            try:
                await _limiter_redis_client.aclose()
            except Exception:
                pass
            _limiter_redis_client = None


_limiter_instance: Optional[RateLimiter] = None


def get_rate_limiter(settings: Any = Depends(get_settings)) -> RateLimiter:
    """Dependency provider returning singleton RateLimiter instance."""
    actual_settings = settings if isinstance(settings, Settings) else get_settings()
    global _limiter_instance
    if _limiter_instance is None or _limiter_instance.settings != actual_settings:
        _limiter_instance = RateLimiter(settings=actual_settings)
    return _limiter_instance


async def shutdown_limiter() -> None:
    """Close rate limiter Redis client on application shutdown."""
    global _limiter_instance, _limiter_redis_client
    if _limiter_instance is not None:
        try:
            await _limiter_instance.aclose()
        except Exception:
            pass
        _limiter_instance = None
    if _limiter_redis_client is not None:
        try:
            await _limiter_redis_client.aclose()
        except Exception:
            pass
        _limiter_redis_client = None
