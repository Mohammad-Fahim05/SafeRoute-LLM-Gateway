"""Unit tests for SafeRoute Prometheus metrics instrumentation."""

import pytest
from prometheus_client import CollectorRegistry

from app.metrics import (
    GatewayMetrics,
    normalize_model,
    normalize_provider,
    normalize_route,
)


@pytest.fixture
def clean_metrics():
    """Create a fresh GatewayMetrics instance with a clean isolated registry."""
    registry = CollectorRegistry()
    return GatewayMetrics(registry=registry)


def test_normalize_route():
    """Verify route normalization bounds cardinality to known gateway endpoints."""
    assert normalize_route("/health") == "/health"
    assert normalize_route("/health/") == "/health"
    assert normalize_route("/ready") == "/ready"
    assert normalize_route("/metrics") == "/metrics"
    assert normalize_route("/v1/chat/completions") == "/v1/chat/completions"
    assert normalize_route("/v1/chat/completions?foo=bar") == "/v1/chat/completions"
    assert normalize_route("/v1/usage/summary") == "/v1/usage/summary"
    assert normalize_route("/v1/usage/export") == "/v1/usage/export"
    assert normalize_route("/docs") == "/docs"
    # Unrecognized routes map to 'other' to prevent unbounded metric label growth
    assert normalize_route("/random/unknown/path") == "other"
    assert normalize_route("/api/malicious/injected/user/id/12345") == "other"


def test_normalize_provider():
    """Verify provider normalization bounds values to known provider adapters."""
    assert normalize_provider("ollama") == "ollama"
    assert normalize_provider("Ollama ") == "ollama"
    assert normalize_provider("mock") == "mock"
    assert normalize_provider("gateway") == "gateway"
    assert normalize_provider("unknown") == "unknown"
    assert normalize_provider("claude") == "unknown"
    assert normalize_provider("gemini") == "unknown"
    assert normalize_provider("some_arbitrary_attacker_provider") == "unknown"
    assert normalize_provider(None) == "unknown"


def test_normalize_model():
    """Verify model normalization bounds values to known catalog models."""
    assert normalize_model("llama3.2:1b") == "llama3.2:1b"
    assert normalize_model("mock-model") == "mock-model"
    assert normalize_model("qwen2.5-coder:7b-instruct-q4_K_M") == "qwen2.5-coder:7b-instruct-q4_K_M"
    assert normalize_model("claude-sonnet-4-6") == "other"
    assert normalize_model("gemini-3.8-flash") == "other"
    assert normalize_model("unregistered-random-model-xyz") == "other"
    assert normalize_model("") == "other"
    assert normalize_model(None) == "other"


def test_record_http_request(clean_metrics):
    """Verify recording HTTP requests updates both counter and duration histogram."""
    clean_metrics.record_http_request(
        route="/v1/chat/completions",
        status=200,
        provider="ollama",
        duration_seconds=0.150,
    )

    out = clean_metrics.export_metrics().decode("utf-8")
    assert 'saferoute_requests_total{provider="ollama",route="/v1/chat/completions",status="200"} 1.0' in out
    assert 'saferoute_request_duration_seconds_count{route="/v1/chat/completions",status="200"} 1.0' in out
    assert 'saferoute_request_duration_seconds_sum{route="/v1/chat/completions",status="200"} 0.15' in out


def test_record_provider_latency_and_errors(clean_metrics):
    """Verify provider duration histograms and error counters."""
    # 1. Success latency
    clean_metrics.record_provider_latency(
        provider="ollama",
        model="llama3.2:1b",
        duration_seconds=0.350,
    )
    # 2. Timeout error
    clean_metrics.record_provider_error(
        provider="ollama",
        error_type="timeout",
    )
    # 3. Server error
    clean_metrics.record_provider_error(
        provider="mock",
        error_type="500 Internal Server Error",
    )
    # 4. Rate limit error
    clean_metrics.record_provider_error(
        provider="gateway",
        error_type="429 Too Many Requests",
    )

    out = clean_metrics.export_metrics().decode("utf-8")
    assert 'saferoute_provider_duration_seconds_count{model="llama3.2:1b",provider="ollama"} 1.0' in out
    assert 'saferoute_provider_errors_total{error_type="timeout",provider="ollama"} 1.0' in out
    assert 'saferoute_provider_errors_total{error_type="server_error",provider="mock"} 1.0' in out
    assert 'saferoute_provider_errors_total{error_type="rate_limit",provider="gateway"} 1.0' in out


def test_record_cache_operations(clean_metrics):
    """Verify exact and semantic cache event counters."""
    clean_metrics.record_cache_operation("exact", "hit")
    clean_metrics.record_cache_operation("exact", "miss")
    clean_metrics.record_cache_operation("exact", "bypass")
    clean_metrics.record_cache_operation("exact", "stale_eviction")

    clean_metrics.record_cache_operation("semantic", "hit")
    clean_metrics.record_cache_operation("semantic", "error")

    out = clean_metrics.export_metrics().decode("utf-8")
    assert 'saferoute_cache_operations_total{cache_type="exact",event="hit"} 1.0' in out
    assert 'saferoute_cache_operations_total{cache_type="exact",event="miss"} 1.0' in out
    assert 'saferoute_cache_operations_total{cache_type="exact",event="bypass"} 1.0' in out
    assert 'saferoute_cache_operations_total{cache_type="exact",event="stale_eviction"} 1.0' in out
    assert 'saferoute_cache_operations_total{cache_type="semantic",event="hit"} 1.0' in out
    assert 'saferoute_cache_operations_total{cache_type="semantic",event="error"} 1.0' in out


def test_record_tokens(clean_metrics):
    """Verify token processing counter tracks input and output tokens with provenance."""
    clean_metrics.record_tokens(
        input_tokens=25,
        output_tokens=75,
        provider="ollama",
        model="llama3.2:1b",
        source="provider_reported",
    )
    clean_metrics.record_tokens(
        input_tokens=10,
        output_tokens=30,
        provider="mock",
        model="mock-model",
        source="mock_estimated",
    )

    out = clean_metrics.export_metrics().decode("utf-8")
    assert 'saferoute_tokens_total{model="llama3.2:1b",provider="ollama",source="provider_reported",type="input"} 25.0' in out
    assert 'saferoute_tokens_total{model="llama3.2:1b",provider="ollama",source="provider_reported",type="output"} 75.0' in out
    assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="input"} 10.0' in out
    assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="output"} 30.0' in out


def test_active_streams_gauge(clean_metrics):
    """Verify gauge accurately tracks active streaming connection lifecycle."""
    clean_metrics.increment_active_streams()
    clean_metrics.increment_active_streams()

    out = clean_metrics.export_metrics().decode("utf-8")
    assert "saferoute_streaming_requests_active 2.0" in out

    clean_metrics.decrement_active_streams()
    out = clean_metrics.export_metrics().decode("utf-8")
    assert "saferoute_streaming_requests_active 1.0" in out

    clean_metrics.decrement_active_streams()
    out = clean_metrics.export_metrics().decode("utf-8")
    assert "saferoute_streaming_requests_active 0.0" in out


def test_rate_limit_and_guardrail_blocks(clean_metrics):
    """Verify rate limit rejections and guardrail block counters."""
    clean_metrics.record_rate_limit_exceeded(policy="fixed_window")
    clean_metrics.record_guardrail_block(stage="input", detector="rule")
    clean_metrics.record_guardrail_block(stage="output", detector="classifier")
    clean_metrics.record_guardrail_block(stage="input", detector="payload_size")

    out = clean_metrics.export_metrics().decode("utf-8")
    assert 'saferoute_rate_limit_exceeded_total{policy="fixed_window"} 1.0' in out
    assert 'saferoute_guardrail_blocks_total{detector="rule",stage="input"} 1.0' in out
    assert 'saferoute_guardrail_blocks_total{detector="classifier",stage="output"} 1.0' in out
    assert 'saferoute_guardrail_blocks_total{detector="payload_size",stage="input"} 1.0' in out


def test_metrics_fail_safe_on_invalid_input(clean_metrics):
    """Verify that bad metric data does not raise uncaught exceptions."""
    # None duration or weird objects should not crash caller
    clean_metrics.record_http_request(
        route=None,  # type: ignore
        status=None,  # type: ignore
        provider=None,
        duration_seconds=0.0,
    )
    clean_metrics.record_tokens(
        input_tokens=None,
        output_tokens=None,
        provider="ollama",
        model="llama3.2:1b",
    )
    # Gauge decrementing below zero is permitted by Gauge type without throwing
    clean_metrics.decrement_active_streams()
    out = clean_metrics.export_metrics()
    assert isinstance(out, bytes)
