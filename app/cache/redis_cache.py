"""Redis-backed exact-match response cache for SafeRoute LLM Gateway."""

import hashlib
import json
from typing import Any, Dict, Optional, Tuple
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import logger

_redis_client: Optional[Redis] = None


def sanitize_redis_url(url: str) -> str:
    """Return a sanitized Redis URL with any password or user credentials masked."""
    if "@" in url:
        prefix, remainder = url.split("://", 1)
        if "@" in remainder:
            creds, host = remainder.split("@", 1)
            return f"{prefix}://***:***@{host}"
    return url


def build_cache_key(
    client_id: str,
    provider: str,
    request: ChatCompletionRequest,
    namespace: str = "v1",
) -> str:
    """Construct a deterministic, isolated SHA-256 cache key from request parameters.

    Key Structure:
      saferoute:{namespace}:exact:{client_id}:{sha256_hash}

    Fields included in canonical representation:
      - namespace/version
      - authenticated client_id (strict isolation)
      - resolved provider name
      - requested model identifier
      - ordered conversation messages (role, content, tool_call_id, tool_calls)
      - temperature
      - max_completion_tokens
      - tools definitions
      - tool_choice policy
    """
    canonical_data = {
        "namespace": namespace,
        "client_id": client_id,
        "provider": provider,
        "model": request.model,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "tool_call_id": m.tool_call_id,
                "tool_calls": [tc.model_dump(exclude_none=True) for tc in m.tool_calls] if m.tool_calls else None,
            }
            for m in request.messages
        ],
        "temperature": request.temperature,
        "max_completion_tokens": request.max_completion_tokens,
        "tools": [t.model_dump(exclude_none=True) for t in request.tools] if request.tools else None,
        "tool_choice": (
            request.tool_choice.model_dump(exclude_none=True)
            if hasattr(request.tool_choice, "model_dump")
            else request.tool_choice
        ),
    }

    canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"))
    key_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"saferoute:{namespace}:exact:{client_id}:{key_hash}"


class ExactResponseCache:
    """Manages Redis connection, cache lookup, serialization, and TTL expiration."""

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

        if not self.settings.cache_enabled:
            return None

        global _redis_client
        if _redis_client is None:
            try:
                _redis_client = from_url(
                    self.settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                )
            except Exception as exc:
                clean_url = sanitize_redis_url(self.settings.redis_url)
                logger.warning(f"Failed to initialize Redis client for {clean_url}: {exc}")
                if self.settings.cache_failure_policy == "fail_closed":
                    raise AppException("Redis cache service unavailable.", status_code=500, error_code="cache_error")
                return None

        self._client = _redis_client
        return self._client

    async def get(self, key: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """Look up a response from Redis.

        Returns:
            Tuple of (deserialized_data, status) where status is one of:
            'hit', 'miss', 'disabled', or 'error'.
        """
        if not self.settings.cache_enabled:
            return None, "disabled"

        try:
            client = await self._get_client()
            if client is None:
                return None, "disabled"

            raw = await client.get(key)
            if raw is None:
                return None, "miss"

            # Parse and validate stored payload
            data = json.loads(raw)
            if not isinstance(data, dict) or "choices" not in data or "model" not in data:
                logger.warning("Corrupted or incompatible cache payload found. Purging key.")
                await client.delete(key)
                return None, "miss"

            return data, "hit"

        except RedisError as exc:
            clean_url = sanitize_redis_url(self.settings.redis_url)
            logger.warning(f"Redis read error on {clean_url}: {type(exc).__name__}")
            if self.settings.cache_failure_policy == "fail_closed":
                raise AppException("Redis cache read failure.", status_code=500, error_code="cache_error")
            return None, "error"
        except Exception as exc:
            logger.warning(f"Unexpected cache read error: {exc}")
            if self.settings.cache_failure_policy == "fail_closed":
                raise AppException("Unexpected cache failure.", status_code=500, error_code="cache_error")
            return None, "error"

    async def set(
        self,
        key: str,
        response: ChatCompletionResponse,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Store an eligible successful response in Redis with finite TTL."""
        if not self.settings.cache_enabled:
            return False

        ttl = ttl_seconds if ttl_seconds is not None else self.settings.cache_ttl_seconds
        try:
            client = await self._get_client()
            if client is None:
                return False

            payload = response.model_dump()
            serialized = json.dumps(payload, separators=(",", ":"))
            await client.set(key, serialized, ex=ttl)
            return True

        except RedisError as exc:
            clean_url = sanitize_redis_url(self.settings.redis_url)
            logger.warning(f"Redis write error on {clean_url}: {type(exc).__name__}")
            if self.settings.cache_failure_policy == "fail_closed":
                raise AppException("Redis cache write failure.", status_code=500, error_code="cache_error")
            return False
        except Exception as exc:
            logger.warning(f"Unexpected cache write error: {exc}")
            if self.settings.cache_failure_policy == "fail_closed":
                raise AppException("Unexpected cache write failure.", status_code=500, error_code="cache_error")
            return False

    async def delete(self, key: str) -> bool:
        """Delete an individual cache key."""
        try:
            client = await self._get_client()
            if client is None:
                return False
            count = await client.delete(key)
            return count > 0
        except Exception as exc:
            logger.warning(f"Redis delete error: {exc}")
            return False

    async def invalidate_client(self, client_id: str, namespace: Optional[str] = None) -> int:
        """Safely invalidate all cache entries for a specific client using SCAN."""
        ns = namespace or self.settings.cache_namespace
        pattern = f"saferoute:{ns}:exact:{client_id}:*"
        return await self._scan_and_delete(pattern)

    async def clear_namespace(self, namespace: Optional[str] = None) -> int:
        """Safely invalidate all cache entries in a namespace using SCAN."""
        ns = namespace or self.settings.cache_namespace
        pattern = f"saferoute:{ns}:exact:*"
        return await self._scan_and_delete(pattern)

    async def _scan_and_delete(self, match_pattern: str) -> int:
        """Helper to scan keys incrementally and delete them without blocking Redis."""
        try:
            client = await self._get_client()
            if client is None:
                return 0

            deleted = 0
            async for k in client.scan_iter(match=match_pattern, count=100):
                await client.delete(k)
                deleted += 1
            return deleted
        except Exception as exc:
            logger.warning(f"Error during cache scan and delete: {exc}")
            return 0

    async def aclose(self) -> None:
        """Close connection to Redis."""
        global _redis_client
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except Exception:
                pass
            _redis_client = None


_cache_instance: Optional[ExactResponseCache] = None


from fastapi import Depends


def get_cache(settings: Any = Depends(get_settings)) -> ExactResponseCache:
    """Dependency provider returning the singleton ExactResponseCache instance."""
    actual_settings = settings if isinstance(settings, Settings) else get_settings()
    global _cache_instance
    if _cache_instance is None or _cache_instance.settings != actual_settings:
        _cache_instance = ExactResponseCache(settings=actual_settings)
    return _cache_instance


async def shutdown_cache() -> None:
    """Close Redis client on application shutdown."""
    global _cache_instance, _redis_client
    if _cache_instance is not None:
        try:
            await _cache_instance.aclose()
        except Exception:
            pass
        _cache_instance = None
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
