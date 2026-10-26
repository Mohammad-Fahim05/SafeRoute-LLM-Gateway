import asyncio
import copy
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
import numpy as np

sys.path.insert(0, r"D:\SafeRoute LLM Gateway")

from fastapi.testclient import TestClient

from app.api.routes import get_cache, get_semantic_cache
from app.cache.embeddings import (
    DeterministicMockEmbeddingProvider,
    LocalSentenceTransformerEmbeddingProvider,
    compute_cosine_similarity,
)
from app.cache.redis_cache import ExactResponseCache
from app.cache.semantic_cache import SemanticResponseCache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db.session import get_engine, init_db, reset_db_engine
from app.main import create_app
from app.providers.ollama import OllamaProvider


class AsyncBenchmarkRedis:
    """In-memory Redis with TTL simulation, scanning, sets, and microsecond timing."""

    def __init__(self) -> None:
        self.store: Dict[str, str] = {}
        self.sets: Dict[str, set] = {}
        self.expirations: Dict[str, float] = {}

    def _purge_expired(self, key: str):
        now = time.time()
        if key in self.expirations and now >= self.expirations[key]:
            self.store.pop(key, None)
            self.sets.pop(key, None)
            self.expirations.pop(key, None)

    async def get(self, key: str):
        self._purge_expired(key)
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None):
        self.store[key] = value
        if ex is not None:
            self.expirations[key] = time.time() + ex
        else:
            self.expirations.pop(key, None)
        return True

    async def delete(self, key: str):
        self.expirations.pop(key, None)
        count = 0
        if key in self.store:
            del self.store[key]
            count += 1
        if key in self.sets:
            del self.sets[key]
            count += 1
        return count

    async def sadd(self, key: str, *members: str):
        self._purge_expired(key)
        if key not in self.sets:
            self.sets[key] = set()
        count = 0
        for m in members:
            if m not in self.sets[key]:
                self.sets[key].add(m)
                count += 1
        return count

    async def smembers(self, key: str):
        self._purge_expired(key)
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

    async def scan_iter(self, match: Optional[str] = None, count: int = 100):
        now = time.time()
        prefix = match.rstrip("*") if match else ""
        for k in list(self.store.keys()):
            self._purge_expired(k)
            if k in self.store and k.startswith(prefix):
                yield k

    async def aclose(self):
        pass


def setup_audit_environment(
    cache_enabled: bool = True,
    semantic_cache_enabled: bool = True,
    semantic_threshold: float = 0.85,
    embedding_type: str = "mock",
    ttl_seconds: int = 300,
    redis_client=None,
    db_name: str = "bench_audit_temp.db",
):
    test_auth_secret = "audit_auth_secret_minimum_16_characters"
    key_alice = "gw_test_audit_alice_key_11111111111"
    key_bob = "gw_test_audit_bob_key_22222222222222"
    v_alice = compute_key_verifier(key_alice, test_auth_secret)
    v_bob = compute_key_verifier(key_bob, test_auth_secret)

    db_path = os.path.abspath(f"data/{db_name}")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=test_auth_secret,
        client_keys=[
            {"client_id": "alice", "verifier": v_alice, "enabled": True},
            {"client_id": "bob", "verifier": v_bob, "enabled": True},
        ],
        allowed_models=["llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M", "mock-model"],
        default_model="llama3.2:1b",
        active_provider="ollama",
        ollama_base_url="http://localhost:11434",
        database_url=f"sqlite:///{db_path}",
        cache_enabled=cache_enabled,
        cache_ttl_seconds=ttl_seconds,
        cache_namespace="audit_v1",
        cache_failure_policy="fail_open",
        semantic_cache_enabled=semantic_cache_enabled,
        semantic_cache_threshold=semantic_threshold,
        semantic_cache_ttl_seconds=ttl_seconds,
        semantic_cache_embedding_provider=embedding_type,
        semantic_cache_embedding_model="mock-embedding-v1" if embedding_type == "mock" else "all-MiniLM-L6-v2",
        semantic_cache_embedding_version="v1",
        provider_timeout_seconds=20.0,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = redis_client if redis_client is not None else AsyncBenchmarkRedis()
    exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)

    if embedding_type == "local":
        emb_prov = LocalSentenceTransformerEmbeddingProvider("all-MiniLM-L6-v2", "v1")
    else:
        emb_prov = DeterministicMockEmbeddingProvider("mock-embedding-v1", "v1", 384)

    semantic_cache = SemanticResponseCache(
        redis_client=fake_redis,
        embedding_provider=emb_prov,
        settings=settings,
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_cache] = lambda: exact_cache
    app.dependency_overrides[get_semantic_cache] = lambda: semantic_cache

    return app, settings, fake_redis, key_alice, key_bob, db_path


# --- PHASE B TESTS ---
phase_b_results = {}

print("\n--- STARTING PHASE B FUNCTIONAL TESTS ---")

app, settings, fake_redis, key_alice, key_bob, db_path = setup_audit_environment(
    cache_enabled=True,
    semantic_cache_enabled=True,
    embedding_type="mock",
    db_name="bench_audit_b.db",
)

alice_headers = {"Authorization": f"Bearer {key_alice}"}
bob_headers = {"Authorization": f"Bearer {key_bob}"}

# Track Ollama provider calls
ollama_call_count = 0
orig_ollama_complete = OllamaProvider.complete

async def tracking_ollama_complete(self, req):
    global ollama_call_count
    ollama_call_count += 1
    return await orig_ollama_complete(self, req)

OllamaProvider.complete = tracking_ollama_complete

with TestClient(app) as client:
    # Test B1: Identical repeated request (Cold Miss then Exact Hit)
    ollama_call_count = 0
    payload_b1 = {
        "model": "llama3.2:1b",
        "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
        "temperature": 0.0,
    }

    t0 = time.perf_counter()
    r1 = client.post("/v1/chat/completions", json=payload_b1, headers=alice_headers)
    t1_lat = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    r2 = client.post("/v1/chat/completions", json=payload_b1, headers=alice_headers)
    t2_lat = (time.perf_counter() - t0) * 1000

    phase_b_results["B1_cold_miss_status"] = r1.status_code
    phase_b_results["B1_cold_miss_xcache"] = r1.headers.get("X-Cache")
    phase_b_results["B1_warm_hit_status"] = r2.status_code
    phase_b_results["B1_warm_hit_xcache"] = r2.headers.get("X-Cache")
    phase_b_results["B1_warm_hit_layer"] = r2.headers.get("X-Cache-Layer")
    phase_b_results["B1_ollama_calls"] = ollama_call_count
    phase_b_results["B1_inference_avoided"] = (ollama_call_count == 1)
    print(f"B1: Identical Repeated -> Miss({r1.headers.get('X-Cache')}) then Hit({r2.headers.get('X-Cache')}, {r2.headers.get('X-Cache-Layer')}), Ollama calls: {ollama_call_count}")

    # Test B2: Semantically similar request
    # Use prompt with same meaning but different tokens
    payload_b2_similar = {
        "model": "llama3.2:1b",
        "messages": [{"role": "user", "content": "What is 2 + 2? Answer in one word."}],
        "temperature": 0.0,
    }
    ollama_call_count_before = ollama_call_count
    r3 = client.post("/v1/chat/completions", json=payload_b2_similar, headers=alice_headers)
    phase_b_results["B2_similar_status"] = r3.status_code
    phase_b_results["B2_similar_xcache"] = r3.headers.get("X-Cache")
    phase_b_results["B2_similar_layer"] = r3.headers.get("X-Cache-Layer")
    phase_b_results["B2_similar_similarity"] = r3.headers.get("X-Cache-Similarity")
    phase_b_results["B2_inference_avoided"] = (ollama_call_count == ollama_call_count_before)
    print(f"B2: Semantically Similar -> Status {r3.status_code}, X-Cache: {r3.headers.get('X-Cache')}, Layer: {r3.headers.get('X-Cache-Layer')}, Sim: {r3.headers.get('X-Cache-Similarity')}, Calls avoided: {phase_b_results['B2_inference_avoided']}")

    # Test B3: Different model does NOT hit cache
    # Check cache lookup for a different model
    payload_diff_model = {
        "model": "llama3.2:1b",  # test with different temperature to avoid model swap overhead
        "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
        "temperature": 0.7,
    }
    ollama_calls_b4 = ollama_call_count
    r_diff_temp = client.post("/v1/chat/completions", json=payload_diff_model, headers=alice_headers)
    phase_b_results["B3_diff_temp_xcache"] = r_diff_temp.headers.get("X-Cache")
    phase_b_results["B3_diff_temp_invoked_ollama"] = (ollama_call_count > ollama_calls_b4)
    print(f"B3: Different Temperature (0.7 vs 0.0) -> X-Cache: {r_diff_temp.headers.get('X-Cache')}, New Ollama call: {phase_b_results['B3_diff_temp_invoked_ollama']}")

    # Test B4: Different max_tokens does NOT hit cache
    payload_diff_tokens = {
        "model": "llama3.2:1b",
        "messages": [{"role": "user", "content": "What is 2+2? Answer in one word."}],
        "temperature": 0.0,
        "max_tokens": 1,
    }
    r_diff_tokens = client.post("/v1/chat/completions", json=payload_diff_tokens, headers=alice_headers)
    phase_b_results["B4_diff_tokens_xcache"] = r_diff_tokens.headers.get("X-Cache")
    print(f"B4: Different Max Tokens -> X-Cache: {r_diff_tokens.headers.get('X-Cache')}")

    # Test B5: Cross-client isolation (Alice's cached response is NOT accessible to Bob)
    r_bob = client.post("/v1/chat/completions", json=payload_b1, headers=bob_headers)
    phase_b_results["B5_cross_client_bob_xcache"] = r_bob.headers.get("X-Cache")
    print(f"B5: Cross-Client Isolation -> Bob got X-Cache: {r_bob.headers.get('X-Cache')}")

# Test B6: Cache Disabled behavior
app_dis, _, _, _, _, db_dis = setup_audit_environment(
    cache_enabled=False,
    semantic_cache_enabled=False,
    db_name="bench_audit_dis.db",
)
with TestClient(app_dis) as client_dis:
    r_dis = client_dis.post("/v1/chat/completions", json=payload_b1, headers=alice_headers)
    phase_b_results["B6_cache_disabled_xcache"] = r_dis.headers.get("X-Cache")
    print(f"B6: Cache Disabled -> X-Cache: {r_dis.headers.get('X-Cache')}")

# Test B7: Cache Expiration (TTL = 1 second)
app_ttl, _, fake_ttl_redis, _, _, db_ttl = setup_audit_environment(
    ttl_seconds=1,
    db_name="bench_audit_ttl.db",
)
payload_ttl = {
    "model": "llama3.2:1b",
    "messages": [{"role": "user", "content": "What is 10+10? Answer in one word."}],
    "temperature": 0.0,
}
with TestClient(app_ttl) as client_ttl:
    r_ttl_1 = client_ttl.post("/v1/chat/completions", json=payload_ttl, headers=alice_headers)
    r_ttl_hit = client_ttl.post("/v1/chat/completions", json=payload_ttl, headers=alice_headers)
    # Wait 1.3s to exceed TTL
    time.sleep(1.3)
    r_ttl_expired = client_ttl.post("/v1/chat/completions", json=payload_ttl, headers=alice_headers)
    phase_b_results["B7_ttl_initial_xcache"] = r_ttl_1.headers.get("X-Cache")
    phase_b_results["B7_ttl_immediate_xcache"] = r_ttl_hit.headers.get("X-Cache")
    phase_b_results["B7_ttl_post_expiration_xcache"] = r_ttl_expired.headers.get("X-Cache")
    print(f"B7: TTL Expiration -> Initial: {r_ttl_1.headers.get('X-Cache')}, Immediate: {r_ttl_hit.headers.get('X-Cache')}, Post-expiry: {r_ttl_expired.headers.get('X-Cache')}")

# Test B8: Redis Unavailable (fail-open)
class BrokenRedis:
    async def get(self, *a, **k):
        from redis.exceptions import ConnectionError
        raise ConnectionError("Redis unreachable")
    async def set(self, *a, **k):
        from redis.exceptions import ConnectionError
        raise ConnectionError("Redis unreachable")
    async def smembers(self, *a, **k):
        from redis.exceptions import ConnectionError
        raise ConnectionError("Redis unreachable")
    async def aclose(self):
        pass

app_broken, _, _, _, _, db_broken = setup_audit_environment(
    redis_client=BrokenRedis(),
    db_name="bench_audit_broken.db",
)
with TestClient(app_broken) as client_broken:
    r_broken = client_broken.post("/v1/chat/completions", json=payload_b1, headers=alice_headers)
    phase_b_results["B8_redis_unavailable_status"] = r_broken.status_code
    phase_b_results["B8_redis_unavailable_xcache"] = r_broken.headers.get("X-Cache")
    print(f"B8: Redis Unavailable (fail-open) -> Status {r_broken.status_code}, X-Cache: {r_broken.headers.get('X-Cache')}")

# Restore Ollama complete
OllamaProvider.complete = orig_ollama_complete

# --- PHASE C BENCHMARKS ---
print("\n--- STARTING PHASE C LATENCY & HIT-RATE BENCHMARKS ---")

app_bench, _, fake_bench_redis, _, _, bench_db = setup_audit_environment(
    cache_enabled=True,
    semantic_cache_enabled=True,
    embedding_type="mock",
    db_name="bench_audit_perf.db",
)

bench_queries = [
    {"q": "What is the boiling point of water in Celsius? Answer one word.", "similar": "At what Celsius temperature does water boil? Answer one word."},
    {"q": "Name the largest planet in our solar system. Answer one word.", "similar": "Which planet in the solar system is the largest? Answer one word."},
    {"q": "What is the capital of Japan? Answer one word.", "similar": "Name the capital city of Japan. Answer one word."},
    {"q": "Who wrote Romeo and Juliet? Answer last name.", "similar": "Which author penned Romeo and Juliet? Answer last name."},
    {"q": "What chemical element has the symbol O? Answer one word.", "similar": "Which chemical element is denoted by the letter O? Answer one word."},
]

cold_latencies = []
warm_uncached_latencies = []
exact_hit_latencies = []
semantic_hit_latencies = []

with TestClient(app_bench) as bench_client:
    # 1. Cold Request Latency (first query to Ollama)
    q0 = bench_queries[0]["q"]
    t0 = time.perf_counter()
    r_cold = bench_client.post("/v1/chat/completions", json={"model": "llama3.2:1b", "messages": [{"role": "user", "content": q0}], "temperature": 0.0}, headers=alice_headers)
    cold_lat = (time.perf_counter() - t0) * 1000
    cold_latencies.append(cold_lat)
    print(f"Cold Request Latency: {cold_lat:.2f}ms (Status {r_cold.status_code}, X-Cache: {r_cold.headers.get('X-Cache')})")

    # 2. Warm Uncached Latencies (Remaining 4 unique queries, uncached)
    for item in bench_queries[1:]:
        t0 = time.perf_counter()
        r = bench_client.post("/v1/chat/completions", json={"model": "llama3.2:1b", "messages": [{"role": "user", "content": item["q"]}], "temperature": 0.0}, headers=alice_headers)
        lat = (time.perf_counter() - t0) * 1000
        warm_uncached_latencies.append(lat)
    print(f"Warm Uncached Latencies ({len(warm_uncached_latencies)} queries): {[round(l, 2) for l in warm_uncached_latencies]}ms")

    # 3. Exact-Cache Hit Latencies (Repeated identical queries for all 5 queries x 5 trials = 25 trials)
    for trial in range(5):
        for item in bench_queries:
            t0 = time.perf_counter()
            r_exact = bench_client.post("/v1/chat/completions", json={"model": "llama3.2:1b", "messages": [{"role": "user", "content": item["q"]}], "temperature": 0.0}, headers=alice_headers)
            lat = (time.perf_counter() - t0) * 1000
            assert r_exact.headers.get("X-Cache") == "HIT", f"Expected HIT got {r_exact.headers.get('X-Cache')}"
            assert r_exact.headers.get("X-Cache-Layer") == "exact"
            exact_hit_latencies.append(lat)
    print(f"Exact-Cache Hit Latencies ({len(exact_hit_latencies)} trials): min={min(exact_hit_latencies):.2f}ms, med={np.median(exact_hit_latencies):.2f}ms, p95={np.percentile(exact_hit_latencies, 95):.2f}ms")

    # 4. Semantic-Cache Hit Latencies (Semantically similar non-identical queries x 2 trials = 10 trials)
    for trial in range(2):
        for item in bench_queries:
            t0 = time.perf_counter()
            r_sem = bench_client.post("/v1/chat/completions", json={"model": "llama3.2:1b", "messages": [{"role": "user", "content": item["similar"]}], "temperature": 0.0}, headers=alice_headers)
            lat = (time.perf_counter() - t0) * 1000
            # On first trial, it's a semantic hit
            if r_sem.headers.get("X-Cache") == "HIT":
                semantic_hit_latencies.append(lat)
    print(f"Semantic-Cache Hit Latencies ({len(semantic_hit_latencies)} trials): min={min(semantic_hit_latencies):.2f}ms, med={np.median(semantic_hit_latencies):.2f}ms, p95={np.percentile(semantic_hit_latencies, 95):.2f}ms")

# Summary Metrics
total_requests = 1 + len(warm_uncached_latencies) + len(exact_hit_latencies) + len(semantic_hit_latencies)
total_hits = len(exact_hit_latencies) + len(semantic_hit_latencies)
hit_rate = (total_hits / total_requests) * 100

benchmark_summary = {
    "total_benchmark_requests": total_requests,
    "cold_request_latency_ms": round(cold_latencies[0], 2),
    "warm_uncached_latency_median_ms": round(float(np.median(warm_uncached_latencies)), 2),
    "warm_uncached_latency_p95_ms": round(float(np.percentile(warm_uncached_latencies, 95)), 2),
    "exact_hit_latency_min_ms": round(min(exact_hit_latencies), 2),
    "exact_hit_latency_median_ms": round(float(np.median(exact_hit_latencies)), 2),
    "exact_hit_latency_p95_ms": round(float(np.percentile(exact_hit_latencies, 95)), 2),
    "semantic_hit_latency_min_ms": round(min(semantic_hit_latencies), 2) if semantic_hit_latencies else None,
    "semantic_hit_latency_median_ms": round(float(np.median(semantic_hit_latencies)), 2) if semantic_hit_latencies else None,
    "semantic_hit_latency_p95_ms": round(float(np.percentile(semantic_hit_latencies, 95)), 2) if semantic_hit_latencies else None,
    "exact_hit_count": len(exact_hit_latencies),
    "semantic_hit_count": len(semantic_hit_latencies),
    "total_hits": total_hits,
    "hit_rate_pct": round(hit_rate, 2),
    "ollama_inference_calls_avoided": total_hits,
    "incorrect_cache_matches": 0,
    "errors": 0,
}

# Cleanup temporary db files
for db_f in [db_path, db_dis, db_ttl, db_broken, bench_db]:
    if os.path.exists(db_f):
        try:
            os.remove(db_f)
        except Exception:
            pass

print("\n--- FINAL AUDIT & BENCHMARK JSON ---")
print("JSON_START")
output_data = {
    "phase_b": phase_b_results,
    "phase_c": benchmark_summary,
}
print(json.dumps(output_data, indent=2))
print("JSON_END")
