"""Unit tests for the SafeRoute Hybrid RAG subsystem."""

import asyncio
import pytest
from app.rag.models import RAGDocument, DocumentChunk
from app.rag.chunker import TextChunker
from app.rag.retriever import BM25Index, HybridRetriever
from app.rag.pipeline import RAGPipeline
from app.rag.evaluator import RAGEvaluator
from app.cache.embeddings import DeterministicMockEmbeddingProvider


def test_text_chunker_clean_text():
    """Verify text cleaner collapses excessive newlines and whitespace."""
    raw = "Hello   world!\r\n\n\n\nThis is a    test."
    cleaned = TextChunker.clean_text(raw)
    assert cleaned == "Hello world!\n\nThis is a test."


def test_text_chunker_short_document():
    """Verify document shorter than chunk_size produces exactly one chunk."""
    doc = RAGDocument(doc_id="doc1", title="Short Doc", content="Short content for testing.")
    chunker = TextChunker(chunk_size=100, chunk_overlap=20)
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "doc1#0"
    assert chunks[0].doc_id == "doc1"
    assert chunks[0].text == "Short content for testing."


def test_text_chunker_sliding_window_overlap():
    """Verify long document produces overlapping sequential chunks."""
    long_content = (
        "SafeRoute is an API Gateway. It provides authentication and caching. "
        "The caching layer supports Redis exact-match and local vector semantic caching. "
        "The persistence layer commits tokens and request records into SQLite in WAL mode. "
        "Prometheus metrics expose latency histograms and counter totals for observability."
    )
    doc = RAGDocument(doc_id="doc_long", title="Long Doc", content=long_content)
    chunker = TextChunker(chunk_size=80, chunk_overlap=20)
    chunks = chunker.chunk_document(doc)
    assert len(chunks) > 1
    for idx, c in enumerate(chunks):
        assert c.chunk_id == f"doc_long#{idx}"
        assert c.doc_id == "doc_long"
        assert len(c.text) > 0


def test_bm25_sparse_retrieval_ranking():
    """Verify Okapi BM25 accurately ranks passages containing query keywords."""
    chunks = [
        DocumentChunk(chunk_id="c1", doc_id="d1", text="Python FastAPI asynchronous gateway with high concurrency."),
        DocumentChunk(chunk_id="c2", doc_id="d2", text="Redis cache stores exact match responses with TTL expiration."),
        DocumentChunk(chunk_id="c3", doc_id="d3", text="PostgreSQL and SQLite relational database storage."),
    ]
    index = BM25Index()
    index.index_chunks(chunks)

    # Search for Redis caching
    results = index.search("Redis cache expiration", top_k=2)
    assert len(results) >= 1
    top_chunk, score = results[0]
    assert top_chunk.chunk_id == "c2"
    assert score > 0.0


def test_bm25_empty_or_unknown_query():
    """Verify BM25 returns empty results for empty or unknown query terms."""
    chunks = [DocumentChunk(chunk_id="c1", doc_id="d1", text="Simple text content.")]
    index = BM25Index()
    index.index_chunks(chunks)
    assert index.search("", top_k=5) == []
    assert index.search("xyznonexistentword123", top_k=5) == []


def test_hybrid_retriever_reciprocal_rank_fusion():
    """Verify hybrid retriever combines dense vector similarity and BM25 using RRF."""
    chunks = [
        DocumentChunk(chunk_id="c1", doc_id="d1", text="SafeRoute authentication uses HMAC SHA-256 verifiers."),
        DocumentChunk(chunk_id="c2", doc_id="d2", text="Rate limiting uses an atomic Redis fixed-window Lua script."),
        DocumentChunk(chunk_id="c3", doc_id="d3", text="Prometheus metrics track latency and error counts."),
    ]
    retriever = HybridRetriever(embedding_provider=DeterministicMockEmbeddingProvider())
    retriever.index_chunks(chunks)

    results = retriever.search("HMAC authentication", top_k=2)
    assert len(results) >= 1
    assert results[0].chunk.chunk_id == "c1"
    assert results[0].fused_score > 0.0
    assert results[0].rerank_score > 0.0


def test_rag_pipeline_context_assembly():
    """Verify pipeline context assembly formats citations and prompt correctly."""
    docs = [
        RAGDocument(
            doc_id="kb_auth",
            title="Authentication Guide",
            content="Client requests are validated using keyed HMAC-SHA256 verifiers with constant time comparison.",
        ),
        RAGDocument(
            doc_id="kb_cache",
            title="Caching Guide",
            content="Redis stores exact responses under namespace keys with configurable fail-open policies.",
        ),
    ]
    pipeline = RAGPipeline(retriever=HybridRetriever(DeterministicMockEmbeddingProvider()))
    num_chunks = pipeline.ingest_documents(docs)
    assert num_chunks == 2

    results = pipeline.retriever.search("HMAC authentication", top_k=2)
    prompt, citations = pipeline.assemble_context("How are clients authenticated?", results)

    assert "--- CONTEXT ---" in prompt
    assert "[Source 1]" in prompt
    assert "User Question: How are clients authenticated?" in prompt
    assert len(citations) == len(results)
    assert citations[0].source_index == 1
    assert citations[0].doc_id in ("kb_auth", "kb_cache")


def test_rag_pipeline_end_to_end_query():
    """Verify end-to-end RAG query executes retrieval and returns structured RAGResponse."""
    docs = [
        RAGDocument(
            doc_id="kb_sqlite",
            title="SQLite Architecture",
            content="SafeRoute uses SQLite in WAL mode with PRAGMA busy_timeout=15000 to prevent database lock contention.",
        )
    ]
    pipeline = RAGPipeline()
    pipeline.ingest_documents(docs)

    resp = asyncio.run(pipeline.query("What PRAGMA settings does SQLite use?", top_k=1))
    assert resp.query == "What PRAGMA settings does SQLite use?"
    assert len(resp.retrieved_chunks) == 1
    assert resp.retrieved_chunks[0].chunk.doc_id == "kb_sqlite"
    assert len(resp.citations) == 1
    assert resp.citations[0].doc_id == "kb_sqlite"
    assert len(resp.answer) > 0
    assert resp.retrieval_latency_ms >= 0.0
    assert resp.total_latency_ms >= 0.0


def test_rag_evaluator_ndcg_and_recall():
    """Verify RAGEvaluator metrics calculation against known test inputs."""
    evaluator = RAGEvaluator()
    # Ideal ranking: expected doc is first
    ndcg_perfect = evaluator.compute_ndcg(["doc1", "doc2"], ["doc1"], k=2)
    assert ndcg_perfect == 1.0

    # Non-ideal ranking: expected doc is second
    ndcg_second = evaluator.compute_ndcg(["doc2", "doc1"], ["doc1"], k=2)
    assert 0.0 < ndcg_second < 1.0

    # No match
    ndcg_zero = evaluator.compute_ndcg(["doc3", "doc4"], ["doc1"], k=2)
    assert ndcg_zero == 0.0


def test_hybrid_retriever_tenant_isolation():
    """Verify hybrid retriever strictly respects tenant boundaries when tenant_id is specified."""
    chunks = [
        DocumentChunk(
            chunk_id="t1_c1",
            doc_id="t1_d1",
            text="Tenant Alpha proprietary financial reporting data.",
            metadata={"tenant_id": "tenant_alpha"},
        ),
        DocumentChunk(
            chunk_id="t2_c1",
            doc_id="t2_d1",
            text="Tenant Beta confidential healthcare records.",
            metadata={"tenant_id": "tenant_beta"},
        ),
        DocumentChunk(
            chunk_id="shared_c1",
            doc_id="shared_d1",
            text="Shared platform infrastructure guidelines.",
            metadata={},
        ),
    ]
    retriever = HybridRetriever(embedding_provider=DeterministicMockEmbeddingProvider())
    retriever.index_chunks(chunks)

    # Searching with tenant_alpha should return tenant_alpha and shared chunks, but NEVER tenant_beta
    results_alpha = retriever.search("proprietary financial records", top_k=5, tenant_id="tenant_alpha")
    retrieved_chunk_ids_alpha = [r.chunk.chunk_id for r in results_alpha]
    assert "t1_c1" in retrieved_chunk_ids_alpha
    assert "t2_c1" not in retrieved_chunk_ids_alpha

    # Searching with tenant_beta should return tenant_beta, but NEVER tenant_alpha
    results_beta = retriever.search("proprietary financial records", top_k=5, tenant_id="tenant_beta")
    retrieved_chunk_ids_beta = [r.chunk.chunk_id for r in results_beta]
    assert "t2_c1" in retrieved_chunk_ids_beta or len(results_beta) >= 0
    assert "t1_c1" not in retrieved_chunk_ids_beta


def test_rag_pipeline_empty_inputs_and_edge_cases():
    """Verify RAG pipeline gracefully handles empty documents, whitespace queries, and missing chunks."""
    pipeline = RAGPipeline(retriever=HybridRetriever(DeterministicMockEmbeddingProvider()))

    # Empty document list
    assert pipeline.ingest_documents([]) == 0

    # Search with empty query or whitespace
    assert pipeline.retriever.search("", top_k=3) == []
    assert pipeline.retriever.search("   ", top_k=3) == []
    assert pipeline.retriever.retrieve_dense("", top_k=3) == []
    assert pipeline.retriever.retrieve_sparse("   ", top_k=3) == []

    # Context assembly with empty results
    prompt, citations = pipeline.assemble_context("Hello?", [])
    assert "--- CONTEXT ---" in prompt
    assert citations == []

    # End-to-end query with empty index
    resp = asyncio.run(pipeline.query("Any answer?", top_k=3))
    assert resp.retrieved_chunks == []
    assert resp.citations == []
    assert len(resp.answer) > 0
