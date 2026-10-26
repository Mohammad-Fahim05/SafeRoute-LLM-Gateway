#!/usr/bin/env python3
"""SafeRoute LLM Gateway — Semantic Cache Benchmark Runner.

Evaluates semantic caching quality, false-positive reuse, false negatives,
embedding latency, and retrieval latency against deterministic datasets.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from app.api.routes import get_cache, get_semantic_cache
from app.cache.embeddings import (
    DeterministicMockEmbeddingProvider,
    LocalSentenceTransformerEmbeddingProvider,
    compute_cosine_similarity,
    get_embedding_provider,
)
from app.cache.redis_cache import ExactResponseCache
from app.cache.semantic_cache import SemanticResponseCache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db.session import get_engine, init_db, reset_db_engine
from app.main import create_app


class InMemoryBenchmarkRedis:
    """In-memory Redis fake with timing hooks for microsecond benchmark tracking."""

    def __init__(self) -> None:
        self.store: Dict[str, str] = {}
        self.sets: Dict[str, set] = {}
        self.ttls: Dict[str, int] = {}
        self.read_latencies_ms: List[float] = []
        self.write_latencies_ms: List[float] = []

    async def get(self, key: str):
        t0 = time.perf_counter()
        val = self.store.get(key)
        self.read_latencies_ms.append((time.perf_counter() - t0) * 1000)
        return val

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        t0 = time.perf_counter()
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        self.write_latencies_ms.append((time.perf_counter() - t0) * 1000)
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
        t0 = time.perf_counter()
        members = set(self.sets.get(key, set()))
        self.read_latencies_ms.append((time.perf_counter() - t0) * 1000)
        return members

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
        return 1

    async def scan_iter(self, match: str = None, count: int = 100):
        prefix = match.rstrip("*") if match else ""
        for k in list(self.store.keys()):
            if k.startswith(prefix):
                yield k

    async def aclose(self):
        pass


def run_benchmark(
    dataset_path: Path,
    embedding_provider_type: str = "mock",
    threshold: float = 0.85,
    output_dir: Path = PROJECT_ROOT / "data" / "evaluation_results",
) -> Dict[str, Any]:
    """Execute semantic cache quality and latency benchmark."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    test_auth_secret = "benchmark_secret_key_16_chars_min"
    client_key = "gw_bench_key_12345678901234567890"
    key_alice = "gw_test_bench_alice_key_11111"
    key_bob = "gw_test_bench_bob_key_22222"
    verifier_alice = compute_key_verifier(key_alice, test_auth_secret)
    verifier_bob = compute_key_verifier(key_bob, test_auth_secret)

    test_db_path = PROJECT_ROOT / "data" / "bench_saferoute.db"
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception:
            pass

    test_db_url = f"sqlite:///{test_db_path.as_posix()}"

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=test_auth_secret,
        client_keys=[
            {"client_id": "alice", "verifier": verifier_alice, "enabled": True},
            {"client_id": "bob", "verifier": verifier_bob, "enabled": True},
        ],
        allowed_models=["mock-model"],
        database_url=test_db_url,
        cache_enabled=True,
        cache_ttl_seconds=300,
        cache_namespace="bench_v1",
        streaming_enabled=True,
        semantic_cache_enabled=True,
        semantic_cache_threshold=threshold,
        semantic_cache_ttl_seconds=300,
        semantic_cache_embedding_provider=embedding_provider_type,
        semantic_cache_embedding_model=(
            "all-MiniLM-L6-v2" if embedding_provider_type == "local" else "mock-embedding-v1"
        ),
        semantic_cache_embedding_version="v1",
        provider_timeout_seconds=2.0,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = InMemoryBenchmarkRedis()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)

    if embedding_provider_type == "local":
        emb_provider = LocalSentenceTransformerEmbeddingProvider(
            model_name="all-MiniLM-L6-v2", version="v1"
        )
    else:
        emb_provider = DeterministicMockEmbeddingProvider(
            model_name="mock-embedding-v1", version="v1", dimension=384
        )

    semantic_cache = SemanticResponseCache(
        redis_client=fake_redis,
        embedding_provider=emb_provider,
        settings=settings,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: exact_cache
    app.dependency_overrides[get_semantic_cache] = lambda: semantic_cache

    results: List[Dict[str, Any]] = []
    embedding_latencies_ms: List[float] = []
    exact_hit_latencies_ms: List[float] = []
    semantic_hit_latencies_ms: List[float] = []
    miss_latencies_ms: List[float] = []

    tp_count = 0
    tn_count = 0
    fp_count = 0
    fn_count = 0

    pairs = dataset.get("pairs", [])

    print(f"\nEvaluating {len(pairs)} benchmark prompt pairs (threshold={threshold}, provider={embedding_provider_type})...\n")

    with TestClient(app) as client:
        for idx, pair in enumerate(pairs, 1):
            pair_id = pair["id"]
            cat = pair["category"]
            seed = pair["seed_prompt"]
            probe = pair["probe_prompt"]
            expected = pair["expected_outcome"]
            should_reuse = pair["should_reuse"]

            seed_client = pair.get("seed_client", "alice")
            probe_client = pair.get("probe_client", "alice")
            seed_hdr = {"Authorization": f"Bearer {key_alice if seed_client == 'alice' else key_bob}"}
            probe_hdr = {"Authorization": f"Bearer {key_alice if probe_client == 'alice' else key_bob}"}

            seed_messages = []
            if pair.get("seed_system"):
                seed_messages.append({"role": "system", "content": pair["seed_system"]})
            seed_messages.append({"role": "user", "content": seed})
            seed_payload = {"model": "mock-model", "messages": seed_messages}
            if pair.get("seed_params"):
                seed_payload.update(pair["seed_params"])

            probe_messages = []
            if pair.get("probe_system"):
                probe_messages.append({"role": "system", "content": pair["probe_system"]})
            probe_messages.append({"role": "user", "content": probe})
            probe_payload = {"model": "mock-model", "messages": probe_messages}
            if pair.get("probe_params"):
                probe_payload.update(pair["probe_params"])

            # 1. Warm-up / seed query
            t0 = time.perf_counter()
            r_seed = client.post(
                "/v1/chat/completions",
                json=seed_payload,
                headers=seed_hdr,
            )
            seed_dur = (time.perf_counter() - t0) * 1000
            assert r_seed.status_code == 200

            # 2. Measure embedding latency specifically on probe prompt
            t_emb0 = time.perf_counter()
            probe_vector = asyncio.run(emb_provider.embed(probe))
            emb_lat = (time.perf_counter() - t_emb0) * 1000
            embedding_latencies_ms.append(emb_lat)

            # 3. Probe query
            t_probe0 = time.perf_counter()
            r_probe = client.post(
                "/v1/chat/completions",
                json=probe_payload,
                headers=probe_hdr,
            )
            probe_dur = (time.perf_counter() - t_probe0) * 1000
            assert r_probe.status_code == 200

            cache_hdr = r_probe.headers.get("X-Cache", "NONE")
            layer_hdr = r_probe.headers.get("X-Cache-Layer", "none")
            sim_hdr = r_probe.headers.get("X-Cache-Similarity")
            similarity = float(sim_hdr) if sim_hdr else 0.0

            # Classify observed outcome
            if cache_hdr == "HIT":
                if layer_hdr == "exact":
                    observed = "exact_hit"
                    exact_hit_latencies_ms.append(probe_dur)
                else:
                    observed = "semantic_hit"
                    semantic_hit_latencies_ms.append(probe_dur)
                reused = True
            elif cache_hdr == "BYPASS":
                observed = "bypass"
                reused = False
                miss_latencies_ms.append(probe_dur)
            else:
                observed = "miss"
                reused = False
                miss_latencies_ms.append(probe_dur)

            # Confusion matrix assessment
            if should_reuse and reused:
                tp_count += 1
                verdict = "CORRECT (TP)"
            elif not should_reuse and not reused:
                tn_count += 1
                verdict = "CORRECT (TN)"
            elif not should_reuse and reused:
                fp_count += 1
                verdict = "FALSE POSITIVE (DANGER)"
            else:
                fn_count += 1
                verdict = "FALSE NEGATIVE"

            print(
                f"[{idx:02d}/{len(pairs):02d}] {pair_id:<32} "
                f"Expected: {expected:<12} Observed: {observed:<12} "
                f"Sim: {similarity:.4f}  Lat: {probe_dur:>6.2f}ms  -> {verdict}"
            )

            results.append({
                "pair_id": pair_id,
                "category": cat,
                "seed_prompt": seed,
                "probe_prompt": probe,
                "expected": expected,
                "observed": observed,
                "should_reuse": should_reuse,
                "reused": reused,
                "similarity": similarity,
                "embedding_latency_ms": round(emb_lat, 2),
                "total_probe_latency_ms": round(probe_dur, 2),
                "verdict": verdict,
            })

    total_pairs = len(pairs)
    accuracy_pct = round(((tp_count + tn_count) / total_pairs) * 100, 2) if total_pairs else 0.0
    fp_rate_pct = round((fp_count / total_pairs) * 100, 2) if total_pairs else 0.0

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "suite_id": dataset.get("suite_id", "semantic_cache_suite"),
        "total_pairs": total_pairs,
        "true_positives": tp_count,
        "true_negatives": tn_count,
        "false_positives": fp_count,
        "false_negatives": fn_count,
        "accuracy_pct": accuracy_pct,
        "false_positive_rate_pct": fp_rate_pct,
        "similarity_threshold": threshold,
        "embedding_provider": embedding_provider_type,
        "latencies": {
            "embedding_mean_ms": round(statistics.mean(embedding_latencies_ms), 2) if embedding_latencies_ms else 0.0,
            "embedding_p50_ms": round(statistics.median(embedding_latencies_ms), 2) if embedding_latencies_ms else 0.0,
            "exact_hit_mean_ms": round(statistics.mean(exact_hit_latencies_ms), 2) if exact_hit_latencies_ms else 0.0,
            "semantic_hit_mean_ms": round(statistics.mean(semantic_hit_latencies_ms), 2) if semantic_hit_latencies_ms else 0.0,
            "provider_miss_mean_ms": round(statistics.mean(miss_latencies_ms), 2) if miss_latencies_ms else 0.0,
        },
    }

    report = {"summary": summary, "cases": results}

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "semantic_cache_benchmark.json"
    md_path = output_dir / "semantic_cache_benchmark.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Markdown Report
    md_lines = [
        "# SafeRoute Semantic Cache Quality & Latency Benchmark Report",
        "",
        f"- **Date (UTC)**: {summary['timestamp_utc']}",
        f"- **Suite ID**: {summary['suite_id']}",
        f"- **Embedding Provider**: `{summary['embedding_provider']}`",
        f"- **Similarity Threshold**: `{summary['similarity_threshold']}`",
        f"- **Total Evaluated Pairs**: `{summary['total_pairs']}`",
        "",
        "## Summary Metrics",
        "",
        "| Metric | Value | Meaning |",
        "| :--- | :--- | :--- |",
        f"| **Overall Accuracy** | **{accuracy_pct}%** | Correct classifications (TP + TN) |",
        f"| **False Positive Count** | **{fp_count}** | Dangerous conflicting reuses (Goal: 0) |",
        f"| **False Positive Rate** | **{fp_rate_pct}%** | Risk of erroneous response generation |",
        f"| **True Positives (Hits)** | {tp_count} | Correctly reused equivalent prompts |",
        f"| **True Negatives (Misses)** | {tn_count} | Correctly rejected conflicting/dissimilar |",
        f"| **False Negatives** | {fn_count} | Missed genuine paraphrases |",
        "",
        "## Latency Profiling",
        "",
        "| Operation / Layer | Mean Latency (ms) | Median p50 (ms) |",
        "| :--- | :--- | :--- |",
        f"| **Embedding Generation** | {summary['latencies']['embedding_mean_ms']} ms | {summary['latencies']['embedding_p50_ms']} ms |",
        f"| **Exact Cache Hit (L1)** | {summary['latencies']['exact_hit_mean_ms']} ms | - |",
        f"| **Semantic Cache Hit (L2)** | {summary['latencies']['semantic_hit_mean_ms']} ms | - |",
        f"| **Provider Execution (Miss)** | {summary['latencies']['provider_miss_mean_ms']} ms | - |",
        "",
        "## Case-by-Case Breakdown",
        "",
        "| ID | Category | Expected | Observed | Similarity | Latency | Outcome |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for c in results:
        md_lines.append(
            f"| `{c['pair_id']}` | {c['category']} | `{c['expected']}` | `{c['observed']}` | {c['similarity']:.4f} | {c['total_probe_latency_ms']} ms | **{c['verdict']}** |"
        )

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    print("\n" + "=" * 76)
    print("Semantic Cache Benchmark Summary:")
    print(f"  Total Pairs Evaluated : {summary['total_pairs']}")
    print(f"  Accuracy              : {accuracy_pct}%")
    print(f"  False Positives (FP)  : {fp_count} (0 is optimal)")
    print(f"  False Negatives (FN)  : {fn_count}")
    print(f"  True Positives (TP)   : {tp_count}")
    print(f"  True Negatives (TN)   : {tn_count}")
    print(f"  Mean Embedding Latency: {summary['latencies']['embedding_mean_ms']} ms")
    print(f"  Semantic Hit Latency  : {summary['latencies']['semantic_hit_mean_ms']} ms")
    print(f"  Reports Generated     : {json_path}")
    print(f"                          {md_path}")
    print("=" * 76)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run semantic cache quality and latency benchmark.")
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(PROJECT_ROOT / "datasets" / "evaluation" / "semantic_cache_suite.json"),
        help="Path to semantic cache benchmark suite JSON.",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "local"],
        default="mock",
        help="Embedding provider for benchmark ('mock' or 'local').",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Similarity threshold for semantic reuse (default: 0.85).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "data" / "evaluation_results"),
        help="Output directory for reports.",
    )

    args = parser.parse_args()
    report = run_benchmark(
        dataset_path=Path(args.dataset),
        embedding_provider_type=args.provider,
        threshold=args.threshold,
        output_dir=Path(args.output_dir),
    )
    return 0 if report["summary"]["false_positives"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
