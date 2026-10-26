"""Integration tests for benchmark script functions and execution."""

import pytest
from scripts.benchmark_load import calculate_percentiles, format_markdown_report


def test_calculate_percentiles_empty():
    """Verify empty list handles percentiles gracefully."""
    res = calculate_percentiles([])
    assert res["p50_ms"] == 0.0
    assert res["mean_ms"] == 0.0


def test_calculate_percentiles_values():
    """Verify accurate percentile calculations for distributed latencies."""
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    res = calculate_percentiles(latencies)
    assert res["min_ms"] == 10.0
    assert res["max_ms"] == 100.0
    assert res["mean_ms"] == 55.0
    assert 50.0 <= res["p50_ms"] <= 60.0
    assert res["p95_ms"] >= 90.0


def test_format_markdown_report():
    """Verify Markdown report generation format."""
    dummy_data = {
        "timestamp": "2026-10-25T12:00:00Z",
        "base_url": "http://localhost:8000",
        "scenarios": [
            {
                "scenario": {
                    "model": "mock-model",
                    "streaming": False,
                    "concurrency": 10,
                    "total_requests": 20,
                    "warmup": 2,
                },
                "summary": {
                    "completed": 20,
                    "successful": 20,
                    "failed": 0,
                    "error_rate_pct": 0.0,
                    "wall_clock_seconds": 0.5,
                    "throughput_rps": 40.0,
                    "cache_hits": 18,
                    "cache_misses": 2,
                    "cache_hit_rate_pct": 90.0,
                },
                "latency_percentiles": {
                    "min_ms": 5.0,
                    "p50_ms": 10.0,
                    "p95_ms": 25.0,
                    "p99_ms": 30.0,
                    "max_ms": 35.0,
                    "mean_ms": 12.0,
                },
                "ttft_percentiles": None,
            }
        ],
    }
    report = format_markdown_report(dummy_data)
    assert "# SafeRoute LLM Gateway" in report
    assert "| `mock-model` | Non-Streaming | 10 | 20 |" in report
    assert "**40.0**" in report
    assert "90.0%" in report
