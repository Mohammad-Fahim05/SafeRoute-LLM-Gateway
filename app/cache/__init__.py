"""Cache module for SafeRoute LLM Gateway."""

from app.cache.embeddings import (
    BaseEmbeddingProvider,
    DeterministicMockEmbeddingProvider,
    LocalSentenceTransformerEmbeddingProvider,
    compute_cosine_similarity,
    get_embedding_provider,
)
from app.cache.redis_cache import (
    ExactResponseCache,
    build_cache_key,
    get_cache,
    sanitize_redis_url,
    shutdown_cache,
)
from app.cache.semantic_cache import (
    SemanticResponseCache,
    get_semantic_cache,
    is_request_eligible_for_semantic_cache,
)

__all__ = [
    "ExactResponseCache",
    "build_cache_key",
    "get_cache",
    "sanitize_redis_url",
    "shutdown_cache",
    "SemanticResponseCache",
    "get_semantic_cache",
    "is_request_eligible_for_semantic_cache",
    "BaseEmbeddingProvider",
    "LocalSentenceTransformerEmbeddingProvider",
    "DeterministicMockEmbeddingProvider",
    "compute_cosine_similarity",
    "get_embedding_provider",
]
