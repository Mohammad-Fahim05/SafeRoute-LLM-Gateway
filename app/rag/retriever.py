"""Hybrid retrieval engine combining Okapi BM25, dense vector cosine similarity, and Reciprocal Rank Fusion."""

import asyncio
import concurrent.futures
import math
import re
from typing import Dict, List, Optional, Tuple
from app.rag.models import DocumentChunk, RetrievalResult
from app.cache.embeddings import (
    BaseEmbeddingProvider,
    DeterministicMockEmbeddingProvider,
    compute_cosine_similarity,
)


class BM25Index:
    """In-memory Okapi BM25 sparse keyword retriever."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus_size: int = 0
        self.avg_doc_len: float = 0.0
        self.doc_lengths: Dict[str, int] = {}
        self.term_freqs: Dict[str, Dict[str, int]] = {}  # chunk_id -> {term: count}
        self.doc_freqs: Dict[str, int] = {}  # term -> count of docs containing term
        self.chunks_by_id: Dict[str, DocumentChunk] = {}

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Simple deterministic word tokenizer and lowercaser."""
        return re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())

    def index_chunks(self, chunks: List[DocumentChunk]) -> None:
        """Build term frequencies, doc frequencies, and length statistics for the corpus."""
        self.chunks_by_id = {c.chunk_id: c for c in chunks}
        self.corpus_size = len(chunks)
        self.doc_lengths.clear()
        self.term_freqs.clear()
        self.doc_freqs.clear()

        total_len = 0
        for chunk in chunks:
            tokens = self.tokenize(chunk.text)
            doc_len = len(tokens)
            self.doc_lengths[chunk.chunk_id] = doc_len
            total_len += doc_len

            freqs: Dict[str, int] = {}
            for t in tokens:
                freqs[t] = freqs.get(t, 0) + 1
            self.term_freqs[chunk.chunk_id] = freqs

            for t in freqs.keys():
                self.doc_freqs[t] = self.doc_freqs.get(t, 0) + 1

        self.avg_doc_len = (total_len / self.corpus_size) if self.corpus_size > 0 else 0.0

    def idf(self, term: str) -> float:
        """Compute standard Robertson-Sparck-Jones Inverse Document Frequency."""
        n_q = self.doc_freqs.get(term, 0)
        # Add 1.0 to ensure positive IDF
        return math.log(((self.corpus_size - n_q + 0.5) / (n_q + 0.5)) + 1.0)

    def score_chunk(self, query_terms: List[str], chunk_id: str) -> float:
        """Calculate Okapi BM25 score for a specific chunk against query terms."""
        doc_len = self.doc_lengths.get(chunk_id, 0)
        if doc_len == 0 or self.avg_doc_len == 0:
            return 0.0

        freqs = self.term_freqs.get(chunk_id, {})
        score = 0.0

        for term in query_terms:
            if term not in freqs:
                continue
            tf = freqs[term]
            idf_val = self.idf(term)
            numerator = tf * (self.k1 + 1.0)
            denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
            score += idf_val * (numerator / denominator)

        return score

    def search(self, query: str, top_k: int = 10, tenant_id: Optional[str] = None) -> List[Tuple[DocumentChunk, float]]:
        """Retrieve top_k chunks sorted by BM25 score descending."""
        query_terms = self.tokenize(query)
        if not query_terms or self.corpus_size == 0:
            return []

        scored: List[Tuple[DocumentChunk, float]] = []
        for chunk_id, chunk in self.chunks_by_id.items():
            if tenant_id is not None:
                chunk_tenant = chunk.metadata.get("tenant_id") or chunk.metadata.get("client_id")
                if chunk_tenant is not None and chunk_tenant != tenant_id:
                    continue
            s = self.score_chunk(query_terms, chunk_id)
            if s > 0.0:
                scored.append((chunk, s))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class HybridRetriever:
    """Hybrid vector + sparse BM25 retriever with Reciprocal Rank Fusion and Reranking."""

    def __init__(
        self,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        bm25_weight: float = 0.5,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> None:
        self.embedding_provider = embedding_provider or DeterministicMockEmbeddingProvider()
        self.bm25_index = BM25Index()
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_k = rrf_k
        self.indexed_chunks: List[DocumentChunk] = []

    def _embed_text(self, text: str) -> List[float]:
        """Generate embedding vector using the provider (handling sync and async implementations)."""
        if hasattr(self.embedding_provider, "_compute_vector"):
            return self.embedding_provider._compute_vector(text)  # type: ignore

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self.embedding_provider.embed(text)).result()
        else:
            return asyncio.run(self.embedding_provider.embed(text))

    def index_chunks(self, chunks: List[DocumentChunk]) -> None:
        """Index chunks for both BM25 and vector search."""
        self.indexed_chunks = chunks
        self.bm25_index.index_chunks(chunks)

        # Precompute embeddings for all chunks if not already present
        for chunk in self.indexed_chunks:
            if chunk.embedding is None:
                chunk.embedding = self._embed_text(chunk.text)

    def retrieve_dense(
        self, query: str, top_k: int = 10, tenant_id: Optional[str] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """Execute dense vector similarity retrieval."""
        if not self.indexed_chunks or not query or not query.strip():
            return []
        query_vec = self._embed_text(query)

        scored: List[Tuple[DocumentChunk, float]] = []
        for chunk in self.indexed_chunks:
            if tenant_id is not None:
                chunk_tenant = chunk.metadata.get("tenant_id") or chunk.metadata.get("client_id")
                if chunk_tenant is not None and chunk_tenant != tenant_id:
                    continue
            if chunk.embedding is not None:
                sim = compute_cosine_similarity(query_vec, chunk.embedding)
                scored.append((chunk, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def retrieve_sparse(
        self, query: str, top_k: int = 10, tenant_id: Optional[str] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """Execute sparse Okapi BM25 keyword retrieval."""
        if not query or not query.strip():
            return []
        return self.bm25_index.search(query, top_k=top_k, tenant_id=tenant_id)

    def fuse_and_rerank(
        self,
        query: str,
        dense_results: List[Tuple[DocumentChunk, float]],
        sparse_results: List[Tuple[DocumentChunk, float]],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """Apply Reciprocal Rank Fusion (RRF) and lexical relevance reranking."""
        candidates: Dict[str, RetrievalResult] = {}

        # 1. Map dense rankings
        for rank, (chunk, score) in enumerate(dense_results, start=1):
            candidates[chunk.chunk_id] = RetrievalResult(
                chunk=chunk,
                vector_score=score,
                vector_rank=rank,
            )

        # 2. Map sparse rankings
        for rank, (chunk, score) in enumerate(sparse_results, start=1):
            if chunk.chunk_id in candidates:
                cand = candidates[chunk.chunk_id]
                cand.bm25_score = score
                cand.bm25_rank = rank
            else:
                candidates[chunk.chunk_id] = RetrievalResult(
                    chunk=chunk,
                    bm25_score=score,
                    bm25_rank=rank,
                )

        # 3. Compute Reciprocal Rank Fusion (RRF)
        # RRF Score = (w_vec / (k + rank_vec)) + (w_bm25 / (k + rank_bm25))
        for cand in candidates.values():
            rrf_vec = (self.vector_weight / (self.rrf_k + cand.vector_rank)) if cand.vector_rank else 0.0
            rrf_bm25 = (self.bm25_weight / (self.rrf_k + cand.bm25_rank)) if cand.bm25_rank else 0.0
            cand.fused_score = rrf_vec + rrf_bm25

            # 4. Reranking step: Combine RRF with exact token overlap boost
            query_tokens = set(self.bm25_index.tokenize(query))
            chunk_tokens = set(self.bm25_index.tokenize(cand.chunk.text))
            overlap_ratio = len(query_tokens & chunk_tokens) / max(len(query_tokens), 1)

            # Final rerank score: 70% fused RRF + 30% lexical overlap boost
            cand.rerank_score = (cand.fused_score * 0.7) + (overlap_ratio * 0.3)

        results = list(candidates.values())
        results.sort(key=lambda r: r.rerank_score, reverse=True)
        return results[:top_k]

    def search(
        self,
        query: str,
        top_k: int = 3,
        candidate_multiplier: int = 3,
        tenant_id: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """End-to-end hybrid search: dense + sparse retrieval, fusion, and reranking."""
        if not query or not query.strip() or not self.indexed_chunks:
            return []
        n_candidates = max(top_k * candidate_multiplier, 10)
        dense_results = self.retrieve_dense(query, top_k=n_candidates, tenant_id=tenant_id)
        sparse_results = self.retrieve_sparse(query, top_k=n_candidates, tenant_id=tenant_id)
        return self.fuse_and_rerank(query, dense_results, sparse_results, top_k=top_k)
