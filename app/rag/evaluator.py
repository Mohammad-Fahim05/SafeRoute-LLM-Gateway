"""Evaluation metrics for RAG retrieval quality: Recall@k, MRR, nDCG@k, and latency."""

import json
import math
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.rag.models import RAGDocument
from app.rag.pipeline import RAGPipeline


class RAGQueryEvaluation(BaseModel):
    query_id: str
    query: str
    expected_doc_ids: List[str]
    retrieved_doc_ids: List[str]
    reciprocal_rank: float
    recall_at_k: float
    ndcg_at_k: float
    latency_ms: float


class RAGSuiteResult(BaseModel):
    total_queries: int
    top_k: int
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    mean_ndcg_at_k: float
    p50_latency_ms: float
    p95_latency_ms: float
    evaluations: List[RAGQueryEvaluation] = Field(default_factory=list)


class RAGEvaluator:
    """Evaluates RAG retrieval effectiveness against labeled benchmark suites."""

    def __init__(self, pipeline: Optional[RAGPipeline] = None) -> None:
        self.pipeline = pipeline or RAGPipeline()

    @staticmethod
    def compute_dcg(relevances: List[int]) -> float:
        """Compute Discounted Cumulative Gain."""
        dcg = 0.0
        for i, rel in enumerate(relevances, start=1):
            dcg += (2**rel - 1) / math.log2(i + 1)
        return dcg

    @classmethod
    def compute_ndcg(cls, retrieved_doc_ids: List[str], expected_doc_ids: List[str], k: int) -> float:
        """Compute Normalized Discounted Cumulative Gain at rank k."""
        actual_relevances = [1 if doc_id in expected_doc_ids else 0 for doc_id in retrieved_doc_ids[:k]]
        dcg = cls.compute_dcg(actual_relevances)

        # Ideal ranking: all relevant documents placed at top
        ideal_relevances = sorted(actual_relevances, reverse=True)
        idcg = cls.compute_dcg(ideal_relevances)

        if idcg == 0.0:
            return 1.0 if not expected_doc_ids else 0.0
        return dcg / idcg

    def evaluate_suite(
        self,
        knowledge_base: List[RAGDocument],
        query_suite: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> RAGSuiteResult:
        """Execute retrieval evaluation across all benchmark queries."""
        # Ingest knowledge base into pipeline
        self.pipeline.ingest_documents(knowledge_base)

        evaluations: List[RAGQueryEvaluation] = []
        latencies: List[float] = []

        for q in query_suite:
            qid = q["query_id"]
            query_str = q["query"]
            expected = q["expected_doc_ids"]

            t0 = time.perf_counter()
            results = self.pipeline.retriever.search(query_str, top_k=top_k)
            latency = (time.perf_counter() - t0) * 1000.0
            latencies.append(latency)

            retrieved_docs = [r.chunk.doc_id for r in results]

            # Calculate Recall@k: 1.0 if any expected doc retrieved in top_k, else 0.0
            hits = [d for d in retrieved_docs if d in expected]
            recall = 1.0 if hits else 0.0

            # Calculate Reciprocal Rank (RR): 1 / first rank of relevant document
            rr = 0.0
            for rank, doc_id in enumerate(retrieved_docs, start=1):
                if doc_id in expected:
                    rr = 1.0 / rank
                    break

            # Calculate nDCG@k
            ndcg = self.compute_ndcg(retrieved_docs, expected, k=top_k)

            evaluations.append(
                RAGQueryEvaluation(
                    query_id=qid,
                    query=query_str,
                    expected_doc_ids=expected,
                    retrieved_doc_ids=retrieved_docs,
                    reciprocal_rank=round(rr, 4),
                    recall_at_k=round(recall, 4),
                    ndcg_at_k=round(ndcg, 4),
                    latency_ms=round(latency, 2),
                )
            )

        n = len(evaluations)
        mrr = sum(e.reciprocal_rank for e in evaluations) / n if n > 0 else 0.0
        m_recall = sum(e.recall_at_k for e in evaluations) / n if n > 0 else 0.0
        m_ndcg = sum(e.ndcg_at_k for e in evaluations) / n if n > 0 else 0.0

        latencies.sort()
        p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

        return RAGSuiteResult(
            total_queries=n,
            top_k=top_k,
            mean_recall_at_k=round(m_recall, 4),
            mean_reciprocal_rank=round(mrr, 4),
            mean_ndcg_at_k=round(m_ndcg, 4),
            p50_latency_ms=round(p50, 2),
            p95_latency_ms=round(p95, 2),
            evaluations=evaluations,
        )
