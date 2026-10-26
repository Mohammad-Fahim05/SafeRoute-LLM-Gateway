"""Embedding provider abstraction and implementations for SafeRoute semantic caching."""

from abc import ABC, abstractmethod
import asyncio
import hashlib
import math
import re
from typing import List, Optional, Sequence
import numpy as np

from app.config import Settings, get_settings
from app.core.errors import AppException
from app.core.logging import logger


def compute_cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    """Calculate the cosine similarity between two numeric vectors.

    Returns a float in [-1.0, 1.0]. Returns 0.0 if either vector has zero magnitude.
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0

    sim = dot / (norm1 * norm2)
    # Clamp against floating point inaccuracies
    return max(-1.0, min(1.0, float(sim)))


class BaseEmbeddingProvider(ABC):
    """Abstract interface for semantic embedding generators."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the underlying embedding model."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Version tag of the embedding representation."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of emitted embedding vectors."""
        pass

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Generate a normalized embedding vector for the given text."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate normalized embedding vectors for a batch of texts."""
        pass


class LocalSentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    """Local SentenceTransformer embedding provider executing offline via CPU."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        version: str = "v1",
    ) -> None:
        self._model_name = model_name
        self._version = version
        self._model = None
        self._dimension = 384
        self._init_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def version(self) -> str:
        return self._version

    @property
    def dimension(self) -> int:
        return self._dimension

    def _load_model(self) -> None:
        """Synchronously load the SentenceTransformer model from local cache."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer

            # Extract model identifier if prefixed with sentence-transformers/
            short_name = self._model_name.split("/")[-1]
            try:
                # First try loading strictly from local files
                self._model = SentenceTransformer(short_name, local_files_only=True)
            except Exception:
                # Fallback to full model name locally
                self._model = SentenceTransformer(self._model_name, local_files_only=True)

            if hasattr(self._model, "get_embedding_dimension"):
                self._dimension = self._model.get_embedding_dimension()
            else:
                self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                f"Loaded local embedding model '{self._model_name}' (dim: {self._dimension})"
            )
        except Exception as exc:
            logger.error(
                f"Failed to load local embedding model '{self._model_name}': {exc}"
            )
            raise AppException(
                f"Embedding model unavailable: {exc}",
                status_code=500,
                error_code="embedding_unavailable",
            )

    async def _ensure_loaded(self) -> None:
        if self._model is None:
            async with self._init_lock:
                if self._model is None:
                    await asyncio.to_thread(self._load_model)

    def _sync_encode(self, texts: List[str]) -> List[List[float]]:
        assert self._model is not None
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [arr.tolist() for arr in embeddings]

    async def embed(self, text: str) -> List[float]:
        await self._ensure_loaded()
        clean_text = text.strip() or " "
        res = await asyncio.to_thread(self._sync_encode, [clean_text])
        return res[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        await self._ensure_loaded()
        clean_texts = [t.strip() or " " for t in texts]
        return await asyncio.to_thread(self._sync_encode, clean_texts)


class DeterministicMockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic hash-based embedding provider for ultra-fast, offline testing.

    Projects token and character n-gram frequencies into a fixed-dimension unit vector.
    Similar sentences yield high cosine similarity; distinct sentences yield low similarity.
    Deliberately differing polarity tokens (e.g., 'not', 'never', 'opposite') reduce similarity.
    """

    def __init__(
        self,
        model_name: str = "mock-embedding-v1",
        version: str = "v1",
        dimension: int = 384,
    ) -> None:
        self._model_name = model_name
        self._version = version
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def version(self) -> str:
        return self._version

    @property
    def dimension(self) -> int:
        return self._dimension

    def _compute_vector(self, text: str) -> List[float]:
        clean = text.lower().strip()
        tokens = re.findall(r"\w+", clean)
        vec = np.zeros(self._dimension, dtype=np.float32)

        if not tokens:
            vec[0] = 1.0
            return vec.tolist()

        # Token-level hashing onto dimension coordinates
        for token in tokens:
            token_hash = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
            idx = token_hash % self._dimension
            sign = 1.0 if (token_hash % 2 == 0) else -1.0
            vec[idx] += sign * 1.5

            # Bigram hashing for word order preservation
            for i in range(len(token) - 2):
                tri = token[i : i + 3]
                tri_hash = int(hashlib.md5(tri.encode("utf-8")).hexdigest()[:8], 16)
                t_idx = tri_hash % self._dimension
                vec[t_idx] += 0.3

        # Word bigrams
        for i in range(len(tokens) - 1):
            pair = f"{tokens[i]}_{tokens[i+1]}"
            pair_hash = int(hashlib.md5(pair.encode("utf-8")).hexdigest()[:8], 16)
            p_idx = pair_hash % self._dimension
            vec[p_idx] += 1.0

        # Contrastive sensitivity: penalize negation terms strongly
        negations = {"not", "never", "no", "opposite", "neither", "nor", "differ", "dont", "wont"}
        neg_count = sum(1 for t in tokens if t in negations)
        if neg_count > 0:
            # Shift negation dimensions to separate positive and negative variants
            for k in range(min(16, self._dimension)):
                vec[k] += neg_count * 2.5

        # Normalize to unit length
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0

        return vec.tolist()

    async def embed(self, text: str) -> List[float]:
        return self._compute_vector(text)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._compute_vector(t) for t in texts]


_provider_instances = {}


def get_embedding_provider(settings: Optional[Settings] = None) -> BaseEmbeddingProvider:
    """Obtain or initialize the configured embedding provider singleton."""
    cfg = settings or get_settings()
    prov_type = cfg.semantic_cache_embedding_provider.lower().strip()
    key = f"{prov_type}:{cfg.semantic_cache_embedding_model}:{cfg.semantic_cache_embedding_version}"

    if key in _provider_instances:
        return _provider_instances[key]

    if prov_type in ("mock", "deterministic", "test"):
        if getattr(cfg, "app_env", "").lower().strip() in ("production", "prod"):
            raise AppException(
                "Mock embedding provider is strictly forbidden in production.",
                status_code=500,
                error_code="configuration_error",
            )
        provider = DeterministicMockEmbeddingProvider(
            model_name=cfg.semantic_cache_embedding_model or "mock-embedding-v1",
            version=cfg.semantic_cache_embedding_version,
            dimension=384,
        )
    else:
        # Default: local SentenceTransformer
        provider = LocalSentenceTransformerEmbeddingProvider(
            model_name=cfg.semantic_cache_embedding_model,
            version=cfg.semantic_cache_embedding_version,
        )

    _provider_instances[key] = provider
    return provider
