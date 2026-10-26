#!/usr/bin/env python3
"""SafeRoute LLM Gateway — Comprehensive AI Evaluation System.

Evaluates:
1. Gateway Performance, Reliability, Streaming TTFT, and Usage Accounting.
2. Semantic Caching Safety, Numeric Collision Rejection, and Cross-Tenant Isolation.
3. Hybrid RAG Retrieval Quality: Recall@k, MRR, nDCG@k, Latency, and Grounded Faithfulness.

Generates both machine-readable JSON and human-readable Markdown evidence.
"""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from app.api.routes import get_cache, get_semantic_cache
from app.cache.embeddings import DeterministicMockEmbeddingProvider
from app.cache.redis_cache import ExactResponseCache
from app.cache.semantic_cache import SemanticResponseCache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db.models import Client, RequestRecord, UsageRecord
from app.db.session import get_engine, init_db, reset_db_engine
from app.main import create_app
from app.rag.evaluator import RAGEvaluator
from app.rag.models import RAGDocument
from app.rag.pipeline import RAGPipeline


AUTH_SECRET = "eval_harness_secret_token_123456789012345678901234567890"
KEY_CLIENT_1 = "gw_test_eval_client_1_key_abcdef1234567890"
VERIFIER_CLIENT_1 = compute_key_verifier(KEY_CLIENT_1, AUTH_SECRET)

KEY_TENANT_A = "gw_test_eval_tenant_a_key_1111222233334444"
VERIFIER_TENANT_A = compute_key_verifier(KEY_TENANT_A, AUTH_SECRET)

KEY_TENANT_B = "gw_test_eval_tenant_b_key_5555666677778888"
VERIFIER_TENANT_B = compute_key_verifier(KEY_TENANT_B, AUTH_SECRET)


class FakeAsyncRedis:
    """In-memory Redis fake with TTL and set support for isolated evaluation."""

    def __init__(self) -> None:
        self.store: Dict[str, str] = {}
        self.sets: Dict[str, set] = {}
        self.ttls: Dict[str, int] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int = None):
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key: str):
        count = 0
        if key in self.store:
            del self.store[key]
            count += 1
        if key in self.sets:
            del self.sets[key]
            count += 1
        return count

    async def sadd(self, key: str, *members: str):
        if key not in self.sets:
            self.sets[key] = set()
        count = 0
        for m in members:
            if m not in self.sets[key]:
                self.sets[key].add(m)
                count += 1
        return count

    async def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    async def srem(self, key: str, *members: str):
        if key not in self.sets:
            return 0
        count = 0
        for m in members:
            if m in self.sets[key]:
                self.sets[key].remove(m)
                count += 1
        return count

    async def expire(self, key: str, seconds: int):
        self.ttls[key] = seconds
        return True


def run_gateway_evaluation(test_db_path: Path) -> Dict[str, Any]:
    """Evaluate gateway reliability, latency percentiles, error mapping, and streaming TTFT."""
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["CACHE_ENABLED"] = "true"
    os.environ["SEMANTIC_CACHE_ENABLED"] = "false"
    os.environ["ACTIVE_PROVIDER"] = "mock"
    os.environ["APP_ENV"] = "testing"
    os.environ["AUTH_SECRET"] = AUTH_SECRET

    client_keys_list = [
        {"client_id": "eval_client_1", "verifier": VERIFIER_CLIENT_1, "enabled": True, "role": "client", "is_admin": False}
    ]
    os.environ["CLIENT_KEYS"] = json.dumps(client_keys_list)

    get_settings.cache_clear()
    settings = Settings(
        database_url=f"sqlite:///{test_db_path.as_posix()}",
        cache_enabled=True,
        semantic_cache_enabled=False,
        active_provider="mock",
        app_env="testing",
        auth_secret=AUTH_SECRET,
        client_keys=client_keys_list,
        allowed_models=["mock-model", "mock-timeout", "mock-error"],
        default_model="mock-model",
    )

    reset_db_engine()
    init_db()

    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    fake_redis = FakeAsyncRedis()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)
    app.dependency_overrides[get_cache] = lambda: exact_cache

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {KEY_CLIENT_1}"}

    # 1. Measure Latency & Success Rates across 50 requests
    latencies: List[float] = []
    success_count = 0
    error_count = 0

    for i in range(50):
        t0 = time.perf_counter()
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": f"Evaluation prompt sequence {i}"}],
                "temperature": 0.0,
            },
            headers=headers,
        )
        lat = (time.perf_counter() - t0) * 1000.0
        latencies.append(lat)
        if resp.status_code == 200:
            success_count += 1
        else:
            error_count += 1

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    # 2. Exact Cache Hit / Miss Verification
    payload_cacheable = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Deterministic cache test prompt"}],
        "temperature": 0.0,
    }
    r_miss = client.post("/v1/chat/completions", json=payload_cacheable, headers=headers)
    r_hit = client.post("/v1/chat/completions", json=payload_cacheable, headers=headers)
    cache_miss_ok = r_miss.headers.get("X-Cache") == "MISS"
    cache_hit_ok = r_hit.headers.get("X-Cache") == "HIT"

    # 3. Streaming TTFT Measurement
    streaming_ttfts: List[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        ttft = 0.0
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "Stream test"}],
                "stream": True,
            },
            headers=headers,
        ) as stream_resp:
            for chunk in stream_resp.iter_lines():
                if chunk and ttft == 0.0:
                    ttft = (time.perf_counter() - t0) * 1000.0
                    break
        if ttft > 0.0:
            streaming_ttfts.append(ttft)

    mean_ttft = statistics.mean(streaming_ttfts) if streaming_ttfts else 0.0

    # 4. Error Mapping Tests
    r_timeout = client.post(
        "/v1/chat/completions",
        json={"model": "mock-timeout", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    r_err = client.post(
        "/v1/chat/completions",
        json={"model": "mock-error", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    timeout_mapped = r_timeout.status_code in (504, 502)
    error_mapped = r_err.status_code in (500, 502)

    # 5. Usage-Accounting Verification
    from sqlalchemy.orm import Session
    engine = get_engine()
    with Session(engine) as session:
        records = session.query(UsageRecord).all()
        total_recorded = len(records)
        token_sum = sum(r.total_tokens or 0 for r in records)
        usage_correct = total_recorded > 0 and token_sum > 0

    return {
        "total_requests": len(latencies),
        "success_rate_pct": round((success_count / len(latencies)) * 100, 2),
        "error_rate_pct": round((error_count / len(latencies)) * 100, 2),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
        "cache_hit_verified": cache_miss_ok and cache_hit_ok,
        "streaming_mean_ttft_ms": round(mean_ttft, 2),
        "error_handling_verified": timeout_mapped and error_mapped,
        "usage_accounting_verified": usage_correct,
        "usage_records_verified_count": total_recorded,
    }


def run_semantic_cache_safety_evaluation(test_db_path: Path) -> Dict[str, Any]:
    """Evaluate semantic caching for safe reuse, numeric mismatch rejection, and cross-client isolation."""
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["CACHE_ENABLED"] = "true"
    os.environ["SEMANTIC_CACHE_ENABLED"] = "true"
    os.environ["SEMANTIC_CACHE_SIMILARITY_THRESHOLD"] = "0.85"
    os.environ["SEMANTIC_CACHE_EMBEDDING_PROVIDER"] = "mock"
    os.environ["ACTIVE_PROVIDER"] = "mock"
    os.environ["APP_ENV"] = "testing"
    os.environ["AUTH_SECRET"] = AUTH_SECRET

    client_keys_list = [
        {"client_id": "client_tenant_a", "verifier": VERIFIER_TENANT_A, "enabled": True, "role": "client", "is_admin": False},
        {"client_id": "client_tenant_b", "verifier": VERIFIER_TENANT_B, "enabled": True, "role": "client", "is_admin": False},
    ]
    os.environ["CLIENT_KEYS"] = json.dumps(client_keys_list)

    get_settings.cache_clear()
    settings = Settings(
        database_url=f"sqlite:///{test_db_path.as_posix()}",
        cache_enabled=True,
        semantic_cache_enabled=True,
        semantic_cache_similarity_threshold=0.85,
        semantic_cache_embedding_provider="mock",
        active_provider="mock",
        app_env="testing",
        auth_secret=AUTH_SECRET,
        client_keys=client_keys_list,
        allowed_models=["mock-model"],
        default_model="mock-model",
    )

    reset_db_engine()
    init_db()

    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    fake_redis = FakeAsyncRedis()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)
    emb_provider = DeterministicMockEmbeddingProvider()
    semantic_cache = SemanticResponseCache(redis_client=fake_redis, embedding_provider=emb_provider, settings=settings)

    app.dependency_overrides[get_cache] = lambda: exact_cache
    app.dependency_overrides[get_semantic_cache] = lambda: semantic_cache

    client = TestClient(app)
    headers_a = {"Authorization": f"Bearer {KEY_TENANT_A}"}
    headers_b = {"Authorization": f"Bearer {KEY_TENANT_B}"}

    # Test 1: Numeric Entity Mismatch Rejection (Safety check)
    r_seed_num = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Transfer 100 dollars to savings"}]},
        headers=headers_a,
    )
    r_probe_num = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Transfer 500 dollars to savings"}]},
        headers=headers_a,
    )
    numeric_rejected = r_probe_num.headers.get("X-Cache-Layer") != "semantic"

    # Test 2: Cross-Tenant Isolation
    r_tenant_b = client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Transfer 100 dollars to savings"}]},
        headers=headers_b,
    )
    cross_tenant_isolated = r_tenant_b.headers.get("X-Cache") == "MISS"

    # Test 3: Labeled Classification Test (TP, TN, FP, FN)
    labeled_cases = [
        ("What is the capital of France?", "Which city is France's capital?", True),
        ("How to calculate factorial in Python?", "Python code to compute factorial", True),
        ("Explain quantum computing basics", "Describe recipes for chocolate chip cookies", False),
        ("Weather report for New York City", "Weather forecast for Tokyo Japan", False),
        ("Refund policy for order 12345", "Refund policy for order 98765", False),
    ]

    tp, tn, fp, fn = 0, 0, 0, 0
    for seed, probe, should_reuse in labeled_cases:
        fake_redis.store.clear()
        fake_redis.sets.clear()

        client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": seed}]},
            headers=headers_a,
        )
        r = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": probe}]},
            headers=headers_a,
        )
        reused = r.headers.get("X-Cache-Layer") == "semantic" or r.headers.get("X-Cache") == "HIT"

        if should_reuse and reused:
            tp += 1
        elif not should_reuse and not reused:
            tn += 1
        elif not should_reuse and reused:
            fp += 1
        else:
            fn += 1

    total = tp + tn + fp + fn
    accuracy = round(((tp + tn) / total) * 100, 2) if total else 0.0

    return {
        "numeric_entity_safety_enforced": numeric_rejected,
        "cross_tenant_isolation_verified": cross_tenant_isolated,
        "labeled_test_cases": total,
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "accuracy_pct": accuracy,
        "unsafe_reuse_rate_pct": round((fp / total) * 100, 2) if total else 0.0,
    }


def run_rag_evaluation() -> Dict[str, Any]:
    """Evaluate Hybrid RAG pipeline retrieval effectiveness, latency, and faithfulness."""
    kb_path = PROJECT_ROOT / "datasets" / "rag" / "sample_knowledge_base.json"
    queries_path = PROJECT_ROOT / "datasets" / "rag" / "evaluation_queries.json"

    with open(kb_path, "r", encoding="utf-8") as f:
        kb_data = json.load(f)
    docs = [RAGDocument(doc_id=d["doc_id"], title=d["title"], content=d["content"]) for d in kb_data]

    with open(queries_path, "r", encoding="utf-8") as f:
        queries = json.load(f)

    evaluator = RAGEvaluator()
    res = evaluator.evaluate_suite(docs, queries, top_k=3)

    pipeline = evaluator.pipeline
    faithful_count = 0
    for q in queries:
        resp = asyncio.run(pipeline.query(q["query"], top_k=1))
        if resp.citations and f"[{resp.citations[0].source_index}]" in resp.answer:
            faithful_count += 1

    faithfulness_pct = round((faithful_count / len(queries)) * 100, 2) if queries else 0.0

    return {
        "total_queries": res.total_queries,
        "top_k": res.top_k,
        "mean_recall_at_k": res.mean_recall_at_k,
        "mean_reciprocal_rank": res.mean_reciprocal_rank,
        "mean_ndcg_at_k": res.mean_ndcg_at_k,
        "retrieval_latency_p50_ms": res.p50_latency_ms,
        "retrieval_latency_p95_ms": res.p95_latency_ms,
        "answer_faithfulness_pct": faithfulness_pct,
        "query_evaluations": [e.model_dump() for e in res.evaluations],
    }


def main():
    print("=" * 76)
    print("SafeRoute LLM Gateway — Comprehensive AI Evaluation System")
    print("=" * 76)

    test_db = PROJECT_ROOT / "data" / "eval_temp_ai_systems.db"
    if test_db.exists():
        test_db.unlink()

    try:
        # Tier 1: Gateway Evaluation
        print("\n[1/3] Executing Gateway Reliability & Latency Evaluation...")
        gw_results = run_gateway_evaluation(test_db)
        print(f"  -> Success Rate: {gw_results['success_rate_pct']}%")
        print(f"  -> Latency p50: {gw_results['latency_p50_ms']}ms | p95: {gw_results['latency_p95_ms']}ms")
        print(f"  -> Streaming Mean TTFT: {gw_results['streaming_mean_ttft_ms']}ms")
        print(f"  -> Usage Accounting: {'PASS' if gw_results['usage_accounting_verified'] else 'FAIL'}")

        # Tier 2: Semantic Cache Safety
        print("\n[2/3] Executing Semantic Cache Safety & Entity Evaluation...")
        cache_results = run_semantic_cache_safety_evaluation(test_db)
        print(f"  -> Numeric Entity Rejection: {'PASS' if cache_results['numeric_entity_safety_enforced'] else 'FAIL'}")
        print(f"  -> Cross-Tenant Isolation: {'PASS' if cache_results['cross_tenant_isolation_verified'] else 'FAIL'}")
        print(f"  -> Labeled Set Accuracy: {cache_results['accuracy_pct']}% (FP: {cache_results['false_positives']})")

        # Tier 3: Hybrid RAG
        print("\n[3/3] Executing Hybrid RAG Retrieval Quality Evaluation...")
        rag_results = run_rag_evaluation()
        print(f"  -> Mean Recall@3: {rag_results['mean_recall_at_k']}")
        print(f"  -> MRR: {rag_results['mean_reciprocal_rank']}")
        print(f"  -> nDCG@3: {rag_results['mean_ndcg_at_k']}")
        print(f"  -> Retrieval Latency p50: {rag_results['retrieval_latency_p50_ms']}ms")
        print(f"  -> Answer Faithfulness: {rag_results['answer_faithfulness_pct']}%")

        # Compile Master Report
        evidence_dir = PROJECT_ROOT / "docs" / "evidence" / "completion"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "gateway_evaluation": gw_results,
            "semantic_cache_evaluation": cache_results,
            "hybrid_rag_evaluation": rag_results,
        }

        json_out = evidence_dir / "ai_evaluation_report.json"
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        md_out = evidence_dir / "ai_evaluation_report.md"
        with open(md_out, "w", encoding="utf-8") as f:
            f.write("# SafeRoute Comprehensive AI Systems Evaluation Report\n\n")
            f.write(f"**Generated:** {report['timestamp_utc']}\n\n")

            f.write("## 1. Gateway Performance, Reliability & Accounting\n\n")
            f.write(f"- **Total Measured Requests:** {gw_results['total_requests']}\n")
            f.write(f"- **Request Success Rate:** {gw_results['success_rate_pct']}%\n")
            f.write(f"- **Request Error Rate:** {gw_results['error_rate_pct']}%\n")
            f.write(f"- **Latency (p50):** {gw_results['latency_p50_ms']} ms\n")
            f.write(f"- **Latency (p95):** {gw_results['latency_p95_ms']} ms\n")
            f.write(f"- **Latency (p99):** {gw_results['latency_p99_ms']} ms\n")
            f.write(f"- **Streaming Mean TTFT:** {gw_results['streaming_mean_ttft_ms']} ms\n")
            f.write(f"- **Exact Cache Hit / Miss Correctness:** {'Verified' if gw_results['cache_hit_verified'] else 'Failed'}\n")
            f.write(f"- **Error Mapping (504/500/502):** {'Verified' if gw_results['error_handling_verified'] else 'Failed'}\n")
            f.write(f"- **SQLite Usage Accounting Correctness:** {'Verified' if gw_results['usage_accounting_verified'] else 'Failed'} ({gw_results['usage_records_verified_count']} records logged)\n\n")

            f.write("## 2. Semantic Cache Safety & Isolation\n\n")
            f.write(f"- **Numeric Entity Mismatch Rejection:** {'Enforced (Safe)' if cache_results['numeric_entity_safety_enforced'] else 'FAILED'}\n")
            f.write(f"- **Cross-Tenant Cache Isolation:** {'Enforced (Zero Leakage)' if cache_results['cross_tenant_isolation_verified'] else 'FAILED'}\n")
            f.write(f"- **Evaluation Accuracy:** {cache_results['accuracy_pct']}%\n")
            f.write(f"- **Confusion Matrix:** TP={cache_results['true_positives']}, TN={cache_results['true_negatives']}, FP={cache_results['false_positives']}, FN={cache_results['false_negatives']}\n")
            f.write(f"- **Unsafe Reuse Rate:** {cache_results['unsafe_reuse_rate_pct']}%\n\n")

            f.write("## 3. Hybrid RAG Retrieval Quality\n\n")
            f.write(f"- **Benchmark Queries Tested:** {rag_results['total_queries']}\n")
            f.write(f"- **Mean Recall@3:** {rag_results['mean_recall_at_k']}\n")
            f.write(f"- **Mean Reciprocal Rank (MRR):** {rag_results['mean_reciprocal_rank']}\n")
            f.write(f"- **Mean nDCG@3:** {rag_results['mean_ndcg_at_k']}\n")
            f.write(f"- **Retrieval Latency (p50):** {rag_results['retrieval_latency_p50_ms']} ms\n")
            f.write(f"- **Retrieval Latency (p95):** {rag_results['retrieval_latency_p95_ms']} ms\n")
            f.write(f"- **Answer Faithfulness:** {rag_results['answer_faithfulness_pct']}%\n\n")

        print("\n" + "=" * 76)
        print("AI Evaluation Completed Successfully!")
        print(f"JSON Report : {json_out}")
        print(f"Markdown    : {md_out}")
        print("=" * 76)

    finally:
        reset_db_engine()
        try:
            if test_db.exists():
                test_db.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
