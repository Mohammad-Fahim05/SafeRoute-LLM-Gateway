"""Integration tests for SafeRoute Hybrid RAG pipeline with mock provider."""

import asyncio
import json
from pathlib import Path
import pytest

from app.rag.models import RAGDocument
from app.rag.chunker import TextChunker
from app.rag.retriever import HybridRetriever
from app.rag.pipeline import RAGPipeline
from app.cache.embeddings import DeterministicMockEmbeddingProvider
from app.providers.mock import MockProvider


def test_rag_pipeline_with_mock_provider_integration():
    """Verify end-to-end RAG pipeline ingestion, retrieval, prompt assembly, and MockProvider execution."""
    kb_path = Path("datasets/rag/sample_knowledge_base.json")
    assert kb_path.exists(), "Sample knowledge base dataset must exist"

    with open(kb_path, "r", encoding="utf-8") as f:
        kb_data = json.load(f)

    docs = [
        RAGDocument(
            doc_id=d["doc_id"],
            title=d["title"],
            content=d["content"],
            metadata=d.get("metadata", {}),
        )
        for d in kb_data
    ]

    mock_provider = MockProvider(
        default_response="SafeRoute centralizes HMAC-SHA256 authentication and rate limiting [1]."
    )
    retriever = HybridRetriever(embedding_provider=DeterministicMockEmbeddingProvider())
    pipeline = RAGPipeline(
        retriever=retriever,
        chunker=TextChunker(chunk_size=400, chunk_overlap=80),
        provider=mock_provider,
    )

    num_chunks = pipeline.ingest_documents(docs)
    assert num_chunks >= len(docs)

    # Execute a query targeting architecture overview
    query = "What technologies and authentication mechanisms power the SafeRoute gateway architecture?"
    response = asyncio.run(pipeline.query(query, top_k=2, model="mock-model"))

    assert response.query == query
    assert len(response.retrieved_chunks) == 2
    # Verify top chunk matches architecture overview topic
    top_doc_id = response.retrieved_chunks[0].chunk.doc_id
    assert "architecture" in top_doc_id or "overview" in top_doc_id

    # Verify context assembly
    assert "--- CONTEXT ---" in response.augmented_prompt
    assert "[Source 1]" in response.augmented_prompt
    assert query in response.augmented_prompt

    # Verify citation attribution
    assert len(response.citations) == 2
    assert response.citations[0].source_index == 1
    assert len(response.citations[0].snippet) > 0

    # Verify mock provider was invoked
    assert mock_provider.call_count == 1
    assert "SafeRoute centralizes HMAC-SHA256 authentication" in response.answer

    # Verify performance latencies
    assert response.retrieval_latency_ms > 0.0
    assert response.generation_latency_ms >= 0.0
    assert response.total_latency_ms >= response.retrieval_latency_ms
