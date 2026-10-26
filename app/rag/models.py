"""Data models and schemas for the SafeRoute Hybrid RAG subsystem."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RAGDocument(BaseModel):
    """Raw input document for knowledge base ingestion."""
    doc_id: str = Field(description="Unique identifier for the document")
    title: str = Field(default="", description="Human-readable title or file name")
    content: str = Field(description="Raw text content of the document")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary document metadata")


class DocumentChunk(BaseModel):
    """A single segmented passage from an ingested document."""
    chunk_id: str = Field(description="Unique identifier for the chunk (e.g. doc1#0)")
    doc_id: str = Field(description="Parent document identifier")
    title: str = Field(default="", description="Parent document title")
    text: str = Field(description="Cleaned passage text content")
    chunk_index: int = Field(default=0, description="Sequential index within parent document")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata inherited or extracted")
    embedding: Optional[List[float]] = Field(default=None, description="Dense vector embedding")
    token_count: int = Field(default=0, description="Estimated token or word count")


class RetrievalResult(BaseModel):
    """Candidate chunk scored by retrieval components."""
    chunk: DocumentChunk
    vector_score: float = Field(default=0.0, description="Dense vector cosine similarity score [0.0, 1.0]")
    bm25_score: float = Field(default=0.0, description="Sparse BM25 lexical score")
    vector_rank: Optional[int] = Field(default=None, description="Rank from dense retrieval (1-indexed)")
    bm25_rank: Optional[int] = Field(default=None, description="Rank from sparse BM25 retrieval (1-indexed)")
    fused_score: float = Field(default=0.0, description="Combined Reciprocal Rank Fusion score")
    rerank_score: float = Field(default=0.0, description="Final score post-reranking")


class Citation(BaseModel):
    """Structured attribution to an evidence passage."""
    source_index: int = Field(description="Citation index referenced in the answer (e.g. [1])")
    doc_id: str
    chunk_id: str
    title: str
    snippet: str


class RAGResponse(BaseModel):
    """Complete structured response from the RAG pipeline."""
    query: str
    retrieved_chunks: List[RetrievalResult] = Field(default_factory=list)
    augmented_prompt: str = Field(description="Full assembled prompt containing context and query")
    answer: str = Field(default="", description="Generated model completion")
    citations: List[Citation] = Field(default_factory=list)
    retrieval_latency_ms: float = Field(default=0.0)
    generation_latency_ms: float = Field(default=0.0)
    total_latency_ms: float = Field(default=0.0)
