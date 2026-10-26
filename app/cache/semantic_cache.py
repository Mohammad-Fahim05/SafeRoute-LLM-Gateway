"""Redis-backed semantic response cache for SafeRoute LLM Gateway."""

import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.cache.embeddings import (
    BaseEmbeddingProvider,
    compute_cosine_similarity,
    get_embedding_provider,
)
from app.cache.redis_cache import sanitize_redis_url
from fastapi import Depends
from app.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import logger

# Regex for detecting sensitive or secret data in user prompts
SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(?:bearer\s+[a-z0-9_\-\.]{20,})\b"),
    re.compile(r"(?i)\b(?:api[_-]?key\s*[:=]\s*['\"]?[a-z0-9_\-\.]{16,}['\"]?)\b"),
    re.compile(r"(?i)\b(?:password\s*[:=]\s*['\"]?\S{6,}['\"]?)\b"),
    re.compile(r"(?i)\b(?:secret\s*[:=]\s*['\"]?\S{8,}['\"]?)\b"),
    re.compile(r"(?i)-----BEGIN\s+[\w\s\-]+KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\beyJ[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\b"),
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
]

# Personalized patterns referring to private, individual user account records
PERSONALIZED_PATTERNS = [
    re.compile(r"(?i)\b(?:my\s+(?:account|order|balance|profile|invoice|billing|password|ssn|credit\s*card|medical\s*record))\b"),
]

# Temporal terms whose answers change over time
TEMPORAL_PHRASES = [
    "current time",
    "what time is it",
    "today's date",
    "what date is today",
    "what is today's date",
    "what day is it",
    "live price",
    "latest price",
    "current price",
    "stock price right now",
    "crypto price right now",
    "breaking news",
    "latest news",
    "weather right now",
    "current weather",
    "today's weather",
    "real-time",
    "traffic right now",
    "live status",
]


def is_request_eligible_for_semantic_cache(
    request: ChatCompletionRequest,
) -> Tuple[bool, Optional[str]]:
    """Determine whether a request qualifies for semantic caching under conservative safety rules.

    Returns:
        (is_eligible, bypass_reason)
    """
    # 1. Streaming requests bypass semantic cache
    if request.stream:
        return False, "streaming_requests_bypass_semantic_cache"

    # 2. Tool definitions and tool_choice bypass
    if request.tools and len(request.tools) > 0:
        return False, "tool_requests_bypass_semantic_cache"

    if request.tool_choice is not None:
        return False, "tool_choice_requests_bypass_semantic_cache"

    # 3. Tool role or tool_calls messages bypass
    for msg in request.messages:
        if msg.role == "tool" or msg.tool_call_id is not None:
            return False, "tool_messages_bypass_semantic_cache"
        if msg.tool_calls and len(msg.tool_calls) > 0:
            return False, "tool_messages_bypass_semantic_cache"
        if msg.content and "data:image/" in msg.content:
            return False, "multimodal_requests_bypass_semantic_cache"

    # 4. Conversation boundary check: Must contain at least one message and final turn must be 'user'
    if not request.messages:
        return False, "empty_messages_list"

    if request.messages[-1].role != "user":
        return False, "final_message_not_user_turn"

    # 4. Sensitive content and credential detection
    full_text = " ".join((m.content or "") for m in request.messages)
    for pat in SENSITIVE_PATTERNS:
        if pat.search(full_text):
            return False, "sensitive_context_bypasses_semantic_cache"

    # 4.1 Personalized private record detection
    for pat in PERSONALIZED_PATTERNS:
        if pat.search(full_text):
            return False, "personalized_context_bypasses_semantic_cache"

    # 5. Temporal / live state terms detection
    text_lower = full_text.lower()
    for phrase in TEMPORAL_PHRASES:
        if phrase in text_lower:
            return False, "temporal_context_bypasses_semantic_cache"

    return True, None


def extract_prompt_features(text: str) -> Dict[str, Any]:
    """Extract critical semantic invariant features (negation, numeric entities, length)."""
    words = set(re.findall(r"\b\w+\b", text.lower()))
    neg_set = {
        "not", "never", "no", "neither", "nor", "opposite",
        "without", "dont", "wont", "cant", "isnt", "arent",
        "wasnt", "werent", "hasnt", "havent", "hadnt",
        "didn't", "didnt", "shouldnt", "shouldn't", "couldnt", "couldn't",
    }
    has_negation = bool(words & neg_set)
    numbers = sorted(re.findall(r"\b\d+(?:\.\d+)?\b", text))
    return {
        "has_negation": has_negation,
        "numbers": numbers,
        "char_length": len(text.strip()),
    }


def extract_prompt_components(request: ChatCompletionRequest) -> Tuple[str, str, str]:
    """Extract (query_text, system_instructions, history_digest) from request.

    - query_text: the latest user message text to be embedded.
    - system_instructions: normalized system / developer instruction string.
    - history_digest: deterministic SHA-256 digest of prior dialogue turns.
    """
    system_parts: List[str] = []
    history_turns: List[Dict[str, str]] = []
    user_turns: List[str] = []

    for msg in request.messages:
        role = (msg.role or "").strip().lower()
        content = (msg.content or "").strip()

        if role in ("system", "developer"):
            system_parts.append(content)
        elif role == "user":
            user_turns.append(content)
            history_turns.append({"role": "user", "content": content})
        elif role == "assistant":
            history_turns.append({"role": "assistant", "content": content})

    query_text = user_turns[-1] if user_turns else ""
    system_instructions = "\n".join(system_parts).strip()

    # Preceding history includes all turns except the final query
    prior_turns = history_turns[:-1] if history_turns else []
    if prior_turns:
        history_raw = json.dumps(prior_turns, sort_keys=True, separators=(",", ":"))
        history_digest = hashlib.sha256(history_raw.encode("utf-8")).hexdigest()
    else:
        history_digest = "none"

    return query_text, system_instructions, history_digest


class SemanticResponseCache:
    """Manages Redis-backed candidate retrieval, similarity evaluation, and isolation."""

    def __init__(
        self,
        redis_client: Optional[Redis] = None,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = redis_client
        self._embedding_provider = embedding_provider

    async def _get_client(self) -> Optional[Redis]:
        """Obtain or lazily initialize the shared Redis async client."""
        if self._client is not None:
            return self._client

        if not self.settings.semantic_cache_enabled:
            return None

        try:
            self._client = from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            return self._client
        except Exception as exc:
            clean_url = sanitize_redis_url(self.settings.redis_url)
            logger.warning(f"Failed to initialize Redis client for semantic cache: {exc}")
            if self.settings.semantic_cache_failure_policy == "fail_closed":
                raise AppException(
                    "Redis semantic cache service unavailable.",
                    status_code=500,
                    error_code="cache_error",
                )
            return None

    def _get_embedding_provider(self) -> BaseEmbeddingProvider:
        if self._embedding_provider is not None:
            return self._embedding_provider
        self._embedding_provider = get_embedding_provider(self.settings)
        return self._embedding_provider

    def _get_index_key(self, client_id: str, model: str) -> str:
        ns = self.settings.cache_namespace
        clean_model = model.replace(":", "_").replace("/", "_")
        return f"saferoute:{ns}:semantic_idx:{client_id}:{clean_model}"

    def _get_entry_key(self, client_id: str, entry_id: str) -> str:
        ns = self.settings.cache_namespace
        return f"saferoute:{ns}:semantic_entry:{client_id}:{entry_id}"

    async def get(
        self,
        client_id: str,
        request: ChatCompletionRequest,
        provider: str,
    ) -> Tuple[Optional[Dict[str, Any]], str, float, Optional[str]]:
        """Perform semantic cache lookup for an incoming request.

        Returns:
            Tuple of (cached_payload, status, similarity_score, reason)
            where status is one of: 'hit', 'miss', 'bypass', 'disabled', or 'error'.
            When status == 'hit', cached_payload contains an internal '_entry_id' field.
        """
        if not self.settings.semantic_cache_enabled:
            return None, "disabled", 0.0, "semantic_cache_disabled"

        # 1. Eligibility Check
        eligible, bypass_reason = is_request_eligible_for_semantic_cache(request)
        if not eligible:
            return None, "bypass", 0.0, bypass_reason

        # 2. Extract prompt components
        query_text, system_instructions, history_digest = extract_prompt_components(request)
        if not query_text:
            return None, "bypass", 0.0, "empty_query_text"

        try:
            client = await self._get_client()
            if client is None:
                return None, "disabled", 0.0, "redis_client_unavailable"

            index_key = self._get_index_key(client_id, request.model)

            # 3. Retrieve candidate IDs from tenant/model index set
            candidate_ids = set()
            if hasattr(client, "smembers"):
                members = await client.smembers(index_key)
                candidate_ids = set(members) if members else set()

            if not candidate_ids:
                return None, "miss", 0.0, "no_candidates_in_index"

            # 4. Generate query embedding
            emb_provider = self._get_embedding_provider()
            query_vector = await emb_provider.embed(query_text)
            curr_model_name = emb_provider.model_name
            curr_version = emb_provider.version

            # 5. Evaluate candidate records
            best_candidate: Optional[Dict[str, Any]] = None
            best_candidate_id: Optional[str] = None
            best_similarity: float = -1.0
            rejection_reason: Optional[str] = None
            dead_ids: List[str] = []

            # Retrieve candidate entries
            for entry_id in list(candidate_ids)[: self.settings.semantic_cache_max_candidates]:
                entry_key = self._get_entry_key(client_id, entry_id)
                raw = await client.get(entry_key)
                if not raw:
                    dead_ids.append(entry_id)
                    continue

                try:
                    cand = json.loads(raw)
                    if not isinstance(cand, dict) or "response" not in cand or "embedding" not in cand:
                        dead_ids.append(entry_id)
                        await client.delete(entry_key)
                        continue

                    # Strict Tenant Isolation Check
                    if cand.get("client_id") != client_id:
                        dead_ids.append(entry_id)
                        continue

                    # Model Matching (Both requested model and actual response model)
                    if cand.get("model") != request.model or cand.get("response", {}).get("model") != request.model:
                        rejection_reason = "model_mismatch"
                        continue

                    # Embedding Model & Version Match
                    if (
                        cand.get("embedding_model") != curr_model_name
                        or cand.get("embedding_version") != curr_version
                    ):
                        rejection_reason = "embedding_version_mismatch"
                        continue

                    # Vector Dimension Consistency Check
                    cand_vector = cand.get("embedding", [])
                    if not isinstance(cand_vector, list) or len(cand_vector) != len(query_vector):
                        dead_ids.append(entry_id)
                        rejection_reason = "vector_dimension_mismatch"
                        continue

                    # Polarity / Negation Consistency Check
                    query_features = extract_prompt_features(query_text)
                    if cand.get("has_negation", False) != query_features["has_negation"]:
                        rejection_reason = "polarity_inversion_mismatch"
                        continue

                    # Numeric Entity Consistency Check
                    if cand.get("numbers", []) != query_features["numbers"]:
                        rejection_reason = "numeric_entity_mismatch"
                        continue

                    # Query Length Disparity Check (Protects against 256-token prefix saturation)
                    cand_len = cand.get("query_length") or cand.get("features", {}).get("char_length", 0)
                    if cand_len > 0:
                        len_diff = abs(len(query_text) - cand_len)
                        if (len_diff / max(len(query_text), cand_len)) > 0.40:
                            rejection_reason = "query_length_disparity"
                            continue

                    # System Prompt Compatibility (Instructions must match exactly)
                    if cand.get("system_instructions", "") != system_instructions:
                        rejection_reason = "system_instructions_mismatch"
                        continue

                    # Conversation History Compatibility
                    if cand.get("history_digest", "none") != history_digest:
                        rejection_reason = "conversation_history_mismatch"
                        continue

                    # Temperature Determinism & Compatibility
                    req_temp = request.temperature if request.temperature is not None else 1.0
                    cand_temp = cand.get("temperature", 1.0)
                    temp_tol = self.settings.semantic_cache_temperature_tolerance
                    if req_temp == 0.0 or cand_temp == 0.0:
                        # Deterministic requests require exact 0.0 temperature match
                        if req_temp != cand_temp:
                            rejection_reason = "temperature_determinism_mismatch"
                            continue
                    elif abs(req_temp - cand_temp) > temp_tol:
                        rejection_reason = "temperature_mismatch"
                        continue

                    # Truncated Candidate Check (Incomplete responses must not be reused for unconstrained requests)
                    cand_finish_reason = (
                        cand.get("finish_reason")
                        or cand.get("response", {}).get("choices", [{}])[0].get("finish_reason")
                    )
                    if cand_finish_reason == "length":
                        cand_max = cand.get("max_tokens")
                        if request.max_completion_tokens is None or (cand_max and request.max_completion_tokens > cand_max):
                            rejection_reason = "truncated_response_incompatible"
                            continue

                    # Max Tokens Constraint Check
                    if request.max_completion_tokens is not None:
                        cand_out_tokens = cand.get("output_tokens", 0)
                        if cand_out_tokens > request.max_completion_tokens:
                            rejection_reason = "max_completion_tokens_exceeded"
                            continue

                    # Compute Cosine Similarity
                    sim = compute_cosine_similarity(query_vector, cand_vector)

                    if sim > best_similarity:
                        best_similarity = sim
                        if sim >= self.settings.semantic_cache_threshold:
                            best_candidate = cand
                            best_candidate_id = entry_id

                except Exception as parse_err:
                    logger.warning(f"Error parsing semantic candidate {entry_id}: {parse_err}")
                    dead_ids.append(entry_id)
                    continue

            # Clean up dead / expired candidate IDs from index set asynchronously
            if dead_ids and hasattr(client, "srem"):
                try:
                    await client.srem(index_key, *dead_ids)
                except Exception:
                    pass

            # 6. Check against similarity threshold
            if best_candidate and best_similarity >= self.settings.semantic_cache_threshold:
                resp_payload = best_candidate["response"]
                if isinstance(resp_payload, dict):
                    resp_payload["_entry_id"] = best_candidate_id
                return resp_payload, "hit", best_similarity, None

            return None, "miss", max(0.0, best_similarity), (rejection_reason or "similarity_below_threshold")

        except RedisError as exc:
            clean_url = sanitize_redis_url(self.settings.redis_url)
            logger.warning(f"Redis read error in semantic cache on {clean_url}: {exc}")
            if self.settings.semantic_cache_failure_policy == "fail_closed":
                raise AppException(
                    "Redis semantic cache read failure.",
                    status_code=500,
                    error_code="cache_error",
                )
            return None, "error", 0.0, "redis_read_error"
        except Exception as exc:
            logger.warning(f"Unexpected error in semantic cache lookup: {exc}")
            if self.settings.semantic_cache_failure_policy == "fail_closed":
                raise AppException(
                    "Unexpected semantic cache failure.",
                    status_code=500,
                    error_code="cache_error",
                )
            return None, "error", 0.0, "lookup_error"

    async def set(
        self,
        client_id: str,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
        provider: str,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Store an eligible response in the semantic cache with its embedding and metadata."""
        if not self.settings.semantic_cache_enabled:
            return False

        # Only store eligible requests
        eligible, _ = is_request_eligible_for_semantic_cache(request)
        if not eligible:
            return False

        # Ensure response has choices and output tokens
        if not response.choices:
            return False

        query_text, system_instructions, history_digest = extract_prompt_components(request)
        if not query_text:
            return False

        ttl = ttl_seconds if ttl_seconds is not None else self.settings.semantic_cache_ttl_seconds
        try:
            client = await self._get_client()
            if client is None:
                return False

            emb_provider = self._get_embedding_provider()
            query_vector = await emb_provider.embed(query_text)

            # Deterministic Entry ID scoped to tenant, model, and canonical prompt
            id_source = f"{client_id}:{request.model}:{system_instructions}:{history_digest}:{query_text}"
            entry_id = hashlib.sha256(id_source.encode("utf-8")).hexdigest()

            output_tokens = (
                response.usage.completion_tokens
                if response.usage and response.usage.completion_tokens is not None
                else 0
            )

            features = extract_prompt_features(query_text)
            finish_reason = response.choices[0].finish_reason if response.choices else "stop"
            record = {
                "entry_id": entry_id,
                "client_id": client_id,
                "model": request.model,
                "provider": provider,
                "embedding_model": emb_provider.model_name,
                "embedding_version": emb_provider.version,
                "system_instructions": system_instructions,
                "history_digest": history_digest,
                "temperature": request.temperature if request.temperature is not None else 1.0,
                "output_tokens": output_tokens,
                "query_length": len(query_text),
                "max_tokens": request.max_completion_tokens,
                "finish_reason": finish_reason,
                "has_negation": features["has_negation"],
                "numbers": features["numbers"],
                "features": features,
                "embedding": query_vector,
                "response": response.model_dump(),
                "created_at": time.time(),
            }

            entry_key = self._get_entry_key(client_id, entry_id)
            serialized = json.dumps(record, separators=(",", ":"))
            await client.set(entry_key, serialized, ex=ttl)

            # Add entry ID to tenant/model index set
            index_key = self._get_index_key(client_id, request.model)
            if hasattr(client, "sadd"):
                # Bound index set size to prevent unbounded growth
                if hasattr(client, "scard") and hasattr(client, "spop"):
                    card = await client.scard(index_key)
                    if card > 500:
                        await client.spop(index_key)

                await client.sadd(index_key, entry_id)
                # Keep index set alive with slightly longer TTL
                if hasattr(client, "expire"):
                    await client.expire(index_key, ttl * 2)

            return True

        except RedisError as exc:
            clean_url = sanitize_redis_url(self.settings.redis_url)
            logger.warning(f"Redis write error in semantic cache on {clean_url}: {exc}")
            if self.settings.semantic_cache_failure_policy == "fail_closed":
                raise AppException(
                    "Redis semantic cache write failure.",
                    status_code=500,
                    error_code="cache_error",
                )
            return False
        except Exception as exc:
            logger.warning(f"Unexpected error in semantic cache set: {exc}")
            if self.settings.semantic_cache_failure_policy == "fail_closed":
                raise AppException(
                    "Unexpected semantic cache failure.",
                    status_code=500,
                    error_code="cache_error",
                )
            return False

    async def delete_entry(self, client_id: str, entry_id: str, model: Optional[str] = None) -> bool:
        """Purge an individual semantic cache entry and remove it from candidate index."""
        try:
            client = await self._get_client()
            if client is None:
                return False

            entry_key = self._get_entry_key(client_id, entry_id)
            deleted = await client.delete(entry_key)

            if model and hasattr(client, "srem"):
                index_key = self._get_index_key(client_id, model)
                await client.srem(index_key, entry_id)

            return deleted > 0
        except Exception as exc:
            logger.warning(f"Error deleting semantic entry {entry_id}: {exc}")
            return False

    async def invalidate_client(self, client_id: str, namespace: Optional[str] = None) -> int:
        """Safely invalidate all semantic cache entries and indices for a specific client."""
        ns = namespace or self.settings.cache_namespace
        pattern_entry = f"saferoute:{ns}:semantic_entry:{client_id}:*"
        pattern_idx = f"saferoute:{ns}:semantic_idx:{client_id}:*"

        deleted = 0
        try:
            client = await self._get_client()
            if client is None:
                return 0

            for pattern in (pattern_entry, pattern_idx):
                if hasattr(client, "scan_iter"):
                    async for k in client.scan_iter(match=pattern, count=100):
                        await client.delete(k)
                        deleted += 1
            return deleted
        except Exception as exc:
            logger.warning(f"Error during client semantic cache invalidation: {exc}")
            return 0

    async def close(self) -> None:
        """Gracefully close Redis connection on application shutdown."""
        if self._client is not None:
            try:
                if hasattr(self._client, "aclose"):
                    await self._client.aclose()
                elif hasattr(self._client, "close"):
                    res = self._client.close()
                    import inspect
                    if inspect.isawaitable(res):
                        await res
            except Exception as exc:
                logger.warning(f"Error closing semantic cache client: {exc}")
            finally:
                self._client = None


_semantic_cache_instance: Optional[SemanticResponseCache] = None


def get_semantic_cache(
    settings: Any = Depends(get_settings),
) -> SemanticResponseCache:
    """Dependency provider returning singleton SemanticResponseCache."""
    global _semantic_cache_instance
    cfg = settings if isinstance(settings, Settings) else get_settings()
    if _semantic_cache_instance is None:
        _semantic_cache_instance = SemanticResponseCache(settings=cfg)
    return _semantic_cache_instance
