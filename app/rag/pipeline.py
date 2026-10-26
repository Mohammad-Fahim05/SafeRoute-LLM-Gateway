"""End-to-end Hybrid RAG pipeline with context assembly, citation attribution, and provider execution."""

import time
from typing import Any, List, Optional, Tuple
from app.rag.chunker import TextChunker
from app.rag.models import (
    Citation,
    DocumentChunk,
    RAGDocument,
    RAGResponse,
    RetrievalResult,
)
from app.rag.retriever import HybridRetriever
from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.providers.base import BaseLLMProvider


class RAGPipeline:
    """Complete, self-contained Hybrid RAG pipeline."""

    def __init__(
        self,
        retriever: Optional[HybridRetriever] = None,
        chunker: Optional[TextChunker] = None,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.retriever = retriever or HybridRetriever()
        self.chunker = chunker or TextChunker()
        self.provider = provider
        self.indexed_documents: List[RAGDocument] = []

    def ingest_documents(self, documents: List[RAGDocument]) -> int:
        """Chunk and index a list of RAG documents. Returns count of indexed chunks."""
        self.indexed_documents.extend(documents)
        all_chunks: List[DocumentChunk] = []
        for doc in documents:
            chunks = self.chunker.chunk_document(doc)
            all_chunks.extend(chunks)

        self.retriever.index_chunks(all_chunks)
        return len(all_chunks)

    @staticmethod
    def assemble_context(query: str, retrieved_chunks: List[RetrievalResult]) -> Tuple[str, List[Citation]]:
        """Construct the grounded context block and structured citation list."""
        context_parts: List[str] = []
        citations: List[Citation] = []

        for idx, result in enumerate(retrieved_chunks, start=1):
            chunk = result.chunk
            header = f"[Source {idx}]: {chunk.title or chunk.doc_id} (ID: {chunk.chunk_id})"
            context_parts.append(f"{header}\n{chunk.text}")

            snippet = chunk.text[:120] + "..." if len(chunk.text) > 120 else chunk.text
            citations.append(
                Citation(
                    source_index=idx,
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    title=chunk.title or chunk.doc_id,
                    snippet=snippet,
                )
            )

        context_str = "\n\n".join(context_parts)
        prompt = (
            "You are a helpful assistant. Use ONLY the following verified context passages to answer the user query. "
            "Cite sources using [1], [2] corresponding to the source index numbers. If the answer cannot be found in "
            "the context, state clearly that the information is unavailable.\n\n"
            f"--- CONTEXT ---\n{context_str}\n--- END CONTEXT ---\n\n"
            f"User Question: {query}\n"
            "Answer:"
        )
        return prompt, citations

    async def query(
        self,
        query_text: str,
        top_k: int = 3,
        model: str = "mock-model",
    ) -> RAGResponse:
        """Execute end-to-end RAG query: retrieve, assemble, generate, and attribute."""
        t0 = time.perf_counter()

        # Step 1: Hybrid Retrieval & Reranking
        retrieved = self.retriever.search(query_text, top_k=top_k)
        t_retrieval = time.perf_counter()
        retrieval_ms = (t_retrieval - t0) * 1000.0

        # Step 2: Context Assembly
        augmented_prompt, citations = self.assemble_context(query_text, retrieved)

        # Step 3: Model Execution (if provider is configured)
        answer = ""
        generation_ms = 0.0

        if self.provider is not None:
            t_gen_start = time.perf_counter()
            req = ChatCompletionRequest(
                model=model,
                messages=[ChatMessage(role="user", content=augmented_prompt)],
                temperature=0.0,
            )
            response = await self.provider.complete(req)
            if response.choices:
                answer = response.choices[0].message.content or ""
            generation_ms = (time.perf_counter() - t_gen_start) * 1000.0
        else:
            # Deterministic offline mock synthesis when provider is omitted
            if retrieved:
                top_source = retrieved[0].chunk
                answer = (
                    f"Based on the provided documentation [1], {top_source.text[:150]}... "
                    f"(Source: {top_source.title or top_source.doc_id})"
                )
            else:
                answer = "The requested information is not available in the ingested context."

        total_ms = (time.perf_counter() - t0) * 1000.0

        return RAGResponse(
            query=query_text,
            retrieved_chunks=retrieved,
            augmented_prompt=augmented_prompt,
            answer=answer,
            citations=citations,
            retrieval_latency_ms=round(retrieval_ms, 2),
            generation_latency_ms=round(generation_ms, 2),
            total_latency_ms=round(total_ms, 2),
        )
