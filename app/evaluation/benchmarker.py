"""Performance benchmarking harness measuring gateway latency, caching efficiency, and throughput."""

import math
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from starlette.testclient import TestClient

from app.cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.evaluation.models import BenchmarkMetrics, BenchmarkScenarioResult
from app.evaluation.runner import (
    EVAL_AUTH_SECRET,
    VALID_EVAL_KEY,
    VALID_VERIFIER,
    FakeEvalLimiterRedis,
    FakeEvalRedis,
)
from app.guardrails import GuardrailEngine, get_guardrail_engine
from app.limiter import RateLimiter, get_rate_limiter
from app.main import create_app
from app.providers import get_mock_provider


def calculate_percentiles(durations_ms: List[float]) -> Dict[str, float]:
    """Calculate mean, min, max, p50 (median), p95, and p99 latency metrics.

    Uses monotonic timestamps and deterministic sorting.
    Handles empty lists and small samples gracefully without crashing.
    """
    if not durations_ms:
        return {
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p50": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }

    sorted_vals = sorted(durations_ms)
    n = len(sorted_vals)
    mean_val = sum(sorted_vals) / n

    # Standard mathematical median
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

    def quantile(q: float) -> float:
        # Nearest-rank method (1-indexed rank ceil(q * n))
        idx = max(0, min(n - 1, math.ceil(q * n) - 1))
        return sorted_vals[idx]

    return {
        "mean": round(mean_val, 2),
        "min": round(sorted_vals[0], 2),
        "max": round(sorted_vals[-1], 2),
        "p50": round(median_val, 2),
        "median": round(median_val, 2),
        "p95": round(quantile(0.95), 2),
        "p99": round(quantile(0.99), 2),
    }


class PerformanceBenchmarker:
    """Runs controlled, deterministic micro-benchmarks across gateway components."""

    def __init__(self, iterations: int = 20) -> None:
        self.iterations = max(5, iterations)

    def run_all(self) -> List[BenchmarkScenarioResult]:
        """Execute the standard benchmark scenarios and return compiled results."""
        results = [
            self.benchmark_cold_vs_warm_cache(),
            self.benchmark_cache_disabled_vs_enabled(),
            self.benchmark_guardrails_overhead(),
            self.benchmark_provider_failure_handling(),
        ]
        return results

    def benchmark_cold_vs_warm_cache(self) -> BenchmarkScenarioResult:
        """Measure cold-cache miss versus warm-cache hit response latency.

        Explicitly isolates the initial cold-cache priming request so that its
        higher latency is NOT mixed into warm-cache hit statistics.
        Tracks actual provider call counts and observed cache headers.
        """
        warm_durations: List[float] = []
        hits = 0
        misses = 0
        success_count = 0
        failure_count = 0

        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "benchmark_cache.db"
        settings = Settings(
            app_env="test",
            auth_enabled=True,
            auth_secret=EVAL_AUTH_SECRET,
            client_keys=[{"client_id": "bench_client", "verifier": VALID_VERIFIER, "enabled": True}],
            database_url=f"sqlite:///{db_path}",
            cache_enabled=True,
            rate_limit_enabled=False,
            guardrails_enabled=False,
        )

        reset_db_engine()
        init_db(get_engine(settings.database_url))

        fake_redis = FakeEvalRedis()
        cache_instance = ExactResponseCache(redis_client=fake_redis, settings=settings)

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_cache] = lambda: cache_instance

        mock_provider = get_mock_provider()
        mock_provider.reset_call_count()

        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Benchmark deterministic cache query"}],
        }

        total_t0 = time.perf_counter()
        with TestClient(app, headers={"Authorization": f"Bearer {VALID_EVAL_KEY}"}) as client:
            # 1. Cold cache priming request (measured separately)
            cold_t0 = time.perf_counter()
            cold_resp = client.post("/v1/chat/completions", json=payload)
            cold_duration_ms = (time.perf_counter() - cold_t0) * 1000.0

            if cold_resp.status_code == 200:
                success_count += 1
                hdr = cold_resp.headers.get("X-Cache")
                if hdr == "HIT":
                    hits += 1
                elif hdr == "MISS":
                    misses += 1
            else:
                failure_count += 1

            # 2. Warm cache requests (only these are included in warm latency statistics)
            for _ in range(self.iterations):
                t0 = time.perf_counter()
                resp = client.post("/v1/chat/completions", json=payload)
                d_ms = (time.perf_counter() - t0) * 1000.0
                warm_durations.append(d_ms)

                if resp.status_code == 200:
                    success_count += 1
                    cache_hdr = resp.headers.get("X-Cache")
                    if cache_hdr == "HIT":
                        hits += 1
                    elif cache_hdr == "MISS":
                        misses += 1
                else:
                    failure_count += 1

        total_time_s = time.perf_counter() - total_t0
        provider_calls = mock_provider.call_count

        reset_db_engine()
        try:
            temp_dir.cleanup()
        except Exception:
            pass

        # Warm latency percentiles strictly reflect warm cache hits
        stats = calculate_percentiles(warm_durations)
        total_cache_requests = hits + misses
        hit_ratio = round((hits / total_cache_requests), 4) if total_cache_requests > 0 else 0.0
        total_executed = 1 + self.iterations
        rps = round(total_executed / total_time_s, 2) if total_time_s > 0 else 0.0

        metrics = BenchmarkMetrics(
            sample_size=self.iterations,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=hits,
            cache_miss_count=misses,
            cache_hit_ratio=hit_ratio,
            mean_latency_ms=stats["mean"],
            p50_latency_ms=stats["p50"],
            median_latency_ms=stats["median"],
            p95_latency_ms=stats["p95"],
            p99_latency_ms=stats["p99"],
            min_latency_ms=stats["min"],
            max_latency_ms=stats["max"],
            throughput_rps=rps,
            provider_calls_count=provider_calls,
            cold_latency_ms=round(cold_duration_ms, 2),
        )

        return BenchmarkScenarioResult(
            scenario_name="warm_cache_hits",
            description="Measures latency reduction when identical requests hit an in-memory Redis cache (cold request #1 followed by warm hits).",
            metrics=metrics,
            notes="Warm statistics isolate cache hits. Provider called once during cold priming. Small local samples are indicative.",
        )

    def benchmark_cache_disabled_vs_enabled(self) -> BenchmarkScenarioResult:
        """Measure gateway latency with exact-match caching completely disabled."""
        durations: List[float] = []
        success_count = 0
        failure_count = 0

        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "benchmark_nocache.db"
        settings = Settings(
            app_env="test",
            auth_enabled=True,
            auth_secret=EVAL_AUTH_SECRET,
            client_keys=[{"client_id": "bench_client", "verifier": VALID_VERIFIER, "enabled": True}],
            database_url=f"sqlite:///{db_path}",
            cache_enabled=False,
            rate_limit_enabled=False,
            guardrails_enabled=False,
        )

        reset_db_engine()
        init_db(get_engine(settings.database_url))

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings

        mock_provider = get_mock_provider()
        mock_provider.reset_call_count()

        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Benchmark uncached request"}],
        }

        total_t0 = time.perf_counter()
        with TestClient(app, headers={"Authorization": f"Bearer {VALID_EVAL_KEY}"}) as client:
            for _ in range(self.iterations):
                t0 = time.perf_counter()
                resp = client.post("/v1/chat/completions", json=payload)
                d_ms = (time.perf_counter() - t0) * 1000.0
                durations.append(d_ms)
                if resp.status_code == 200:
                    success_count += 1
                else:
                    failure_count += 1

        total_time_s = time.perf_counter() - total_t0
        provider_calls = mock_provider.call_count

        reset_db_engine()
        try:
            temp_dir.cleanup()
        except Exception:
            pass

        stats = calculate_percentiles(durations)
        rps = round(self.iterations / total_time_s, 2) if total_time_s > 0 else 0.0

        metrics = BenchmarkMetrics(
            sample_size=self.iterations,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=0,
            cache_miss_count=0,
            cache_hit_ratio=0.0,
            mean_latency_ms=stats["mean"],
            p50_latency_ms=stats["p50"],
            median_latency_ms=stats["median"],
            p95_latency_ms=stats["p95"],
            p99_latency_ms=stats["p99"],
            min_latency_ms=stats["min"],
            max_latency_ms=stats["max"],
            throughput_rps=rps,
            provider_calls_count=provider_calls,
        )

        return BenchmarkScenarioResult(
            scenario_name="cache_disabled_baseline",
            description="Measures baseline gateway execution latency with caching completely disabled (provider invoked on every request).",
            metrics=metrics,
            notes="Every request invokes MockProvider and records to SQLite. Small local samples are indicative.",
        )

    def benchmark_guardrails_overhead(self) -> BenchmarkScenarioResult:
        """Measure gateway latency overhead when input and output guardrail rules are actively evaluated."""
        durations: List[float] = []
        success_count = 0
        failure_count = 0

        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "benchmark_guardrails.db"
        settings = Settings(
            app_env="test",
            auth_enabled=True,
            auth_secret=EVAL_AUTH_SECRET,
            client_keys=[{"client_id": "bench_client", "verifier": VALID_VERIFIER, "enabled": True}],
            database_url=f"sqlite:///{db_path}",
            cache_enabled=False,
            rate_limit_enabled=False,
            guardrails_enabled=True,
            guardrails_rules=[
                {"rule_id": "r1", "pattern": "BLOCKED_REGEX_[0-9]+", "match_type": "regex", "stage": "both"},
                {"rule_id": "r2", "pattern": "DROP DATABASE", "match_type": "contains", "stage": "input"},
                {"rule_id": "r3", "pattern": "CONFIDENTIAL", "match_type": "keyword", "stage": "output"},
            ],
        )

        reset_db_engine()
        init_db(get_engine(settings.database_url))

        guardrails = GuardrailEngine(settings=settings)

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_guardrail_engine] = lambda: guardrails

        mock_provider = get_mock_provider()
        mock_provider.reset_call_count()

        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Benchmark safe input undergoing multi-rule guardrail inspection"}],
        }

        total_t0 = time.perf_counter()
        with TestClient(app, headers={"Authorization": f"Bearer {VALID_EVAL_KEY}"}) as client:
            for _ in range(self.iterations):
                t0 = time.perf_counter()
                resp = client.post("/v1/chat/completions", json=payload)
                d_ms = (time.perf_counter() - t0) * 1000.0
                durations.append(d_ms)
                if resp.status_code == 200:
                    success_count += 1
                else:
                    failure_count += 1

        total_time_s = time.perf_counter() - total_t0
        provider_calls = mock_provider.call_count

        reset_db_engine()
        try:
            temp_dir.cleanup()
        except Exception:
            pass

        stats = calculate_percentiles(durations)
        rps = round(self.iterations / total_time_s, 2) if total_time_s > 0 else 0.0

        metrics = BenchmarkMetrics(
            sample_size=self.iterations,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=0,
            cache_miss_count=0,
            cache_hit_ratio=0.0,
            mean_latency_ms=stats["mean"],
            p50_latency_ms=stats["p50"],
            median_latency_ms=stats["median"],
            p95_latency_ms=stats["p95"],
            p99_latency_ms=stats["p99"],
            min_latency_ms=stats["min"],
            max_latency_ms=stats["max"],
            throughput_rps=rps,
            provider_calls_count=provider_calls,
        )

        return BenchmarkScenarioResult(
            scenario_name="guardrails_active_overhead",
            description="Measures latency when incoming prompts and outgoing completions are inspected against multiple regex/keyword rules.",
            metrics=metrics,
            notes="All requests contain safe text passing inspection. Small local samples are indicative.",
        )

    def benchmark_provider_failure_handling(self) -> BenchmarkScenarioResult:
        """Measure gateway latency and error normalization when upstream provider simulates immediate failure."""
        durations: List[float] = []
        success_count = 0
        failure_count = 0

        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "benchmark_failure.db"
        settings = Settings(
            app_env="test",
            auth_enabled=True,
            auth_secret=EVAL_AUTH_SECRET,
            client_keys=[{"client_id": "bench_client", "verifier": VALID_VERIFIER, "enabled": True}],
            allowed_models=["mock-model", "mock-error"],
            database_url=f"sqlite:///{db_path}",
            cache_enabled=False,
            rate_limit_enabled=False,
            guardrails_enabled=False,
        )

        reset_db_engine()
        init_db(get_engine(settings.database_url))

        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings

        mock_provider = get_mock_provider()
        mock_provider.reset_call_count()

        payload = {
            "model": "mock-error",
            "messages": [{"role": "user", "content": "Trigger failure"}],
        }

        total_t0 = time.perf_counter()
        with TestClient(app, headers={"Authorization": f"Bearer {VALID_EVAL_KEY}"}) as client:
            for _ in range(self.iterations):
                t0 = time.perf_counter()
                resp = client.post("/v1/chat/completions", json=payload)
                d_ms = (time.perf_counter() - t0) * 1000.0
                durations.append(d_ms)
                # For this failure benchmark, receiving the expected HTTP 502 counts as handled
                if resp.status_code == 502:
                    success_count += 1
                else:
                    failure_count += 1

        total_time_s = time.perf_counter() - total_t0
        provider_calls = mock_provider.call_count

        reset_db_engine()
        try:
            temp_dir.cleanup()
        except Exception:
            pass

        stats = calculate_percentiles(durations)
        rps = round(self.iterations / total_time_s, 2) if total_time_s > 0 else 0.0

        metrics = BenchmarkMetrics(
            sample_size=self.iterations,
            success_count=success_count,
            failure_count=failure_count,
            cache_hit_count=0,
            cache_miss_count=0,
            cache_hit_ratio=0.0,
            mean_latency_ms=stats["mean"],
            p50_latency_ms=stats["p50"],
            median_latency_ms=stats["median"],
            p95_latency_ms=stats["p95"],
            p99_latency_ms=stats["p99"],
            min_latency_ms=stats["min"],
            max_latency_ms=stats["max"],
            throughput_rps=rps,
            provider_calls_count=provider_calls,
        )

        return BenchmarkScenarioResult(
            scenario_name="provider_error_handling",
            description="Measures gateway latency and structured error generation when the upstream provider fails with an internal error (mock-error).",
            metrics=metrics,
            notes="Verifies gateway quickly normalizes provider 500 error to HTTP 502 Bad Gateway. Small local samples are indicative.",
        )
