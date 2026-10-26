"""Prometheus metrics instrumentation for SafeRoute LLM Gateway.

Provides standard Prometheus metric types (Counter, Histogram, Gauge) with
strictly bounded-cardinality labels, fail-safe exception handling, and
privacy preservation (zero client IDs, prompts, API keys, or raw payloads).
"""

import logging
from typing import Optional, Set, Union
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger("saferoute.metrics")

# Canonical allowed routes for bounded route labels
ALLOWED_ROUTES: Set[str] = {
    "/health",
    "/ready",
    "/metrics",
    "/v1/chat/completions",
    "/v1/usage/summary",
    "/v1/usage/export",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# Known providers for bounded provider labels
KNOWN_PROVIDERS: Set[str] = {
    "ollama",
    "mock",
    "gateway",
    "unknown",
}

# Known models for bounded model labels
KNOWN_MODELS: Set[str] = {
    "mock-model",
    "mock-timeout",
    "mock-error",
    "mock-malformed",
    "mock-rate-limit",
    "mock-auth-error",
    "mock-server-error",
    "llama3.2:1b",
    "qwen2.5-coder:7b-instruct-q4_K_M",
    "llama3.2",
    "phi3",
    "mistral",
}

# Standard latency histogram buckets (in seconds)
HTTP_DURATION_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0
)

PROVIDER_DURATION_BUCKETS = (
    0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0
)


def normalize_route(path: str) -> str:
    """Normalize raw request path to a bounded set of known routes."""
    clean_path = path.split("?")[0].rstrip("/") or "/"
    if clean_path in ALLOWED_ROUTES:
        return clean_path
    return "other"


def normalize_provider(provider: Optional[str]) -> str:
    """Normalize provider name to bounded set."""
    if not provider:
        return "unknown"
    p = str(provider).lower().strip()
    return p if p in KNOWN_PROVIDERS else "unknown"


def normalize_model(model: Optional[str]) -> str:
    """Normalize model identifier to bounded set, preventing label explosion."""
    if not model:
        return "other"
    m = str(model).strip()
    return m if m in KNOWN_MODELS else "other"


class GatewayMetrics:
    """Encapsulates Prometheus registry and metric collectors for SafeRoute."""

    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self.registry = registry or CollectorRegistry()

        # 1. Total HTTP Requests Counter
        self.requests_total = Counter(
            "saferoute_requests_total",
            "Total HTTP requests processed by the gateway",
            ["route", "status", "provider"],
            registry=self.registry,
        )

        # 2. Total Request Duration Histogram
        self.request_duration_seconds = Histogram(
            "saferoute_request_duration_seconds",
            "Total gateway HTTP request duration in seconds",
            ["route", "status"],
            buckets=HTTP_DURATION_BUCKETS,
            registry=self.registry,
        )

        # 3. Upstream Provider Duration Histogram
        self.provider_duration_seconds = Histogram(
            "saferoute_provider_duration_seconds",
            "Upstream provider call duration in seconds",
            ["provider", "model"],
            buckets=PROVIDER_DURATION_BUCKETS,
            registry=self.registry,
        )

        # 4. Upstream Provider Errors Counter
        self.provider_errors_total = Counter(
            "saferoute_provider_errors_total",
            "Total upstream provider errors, timeouts, and failures",
            ["provider", "error_type"],
            registry=self.registry,
        )

        # 5. Cache Operations Counter (Exact and Semantic)
        self.cache_operations_total = Counter(
            "saferoute_cache_operations_total",
            "Total cache operations across exact and semantic cache layers",
            ["cache_type", "event"],
            registry=self.registry,
        )

        # 6. Tokens Processed Counter
        self.tokens_total = Counter(
            "saferoute_tokens_total",
            "Total token counts processed by the gateway",
            ["type", "provider", "model", "source"],
            registry=self.registry,
        )

        # 7. Active Streaming Requests Gauge
        self.streaming_requests_active = Gauge(
            "saferoute_streaming_requests_active",
            "Number of currently active streaming chat completion connections",
            registry=self.registry,
        )

        # 8. Rate Limit Exceeded Counter
        self.rate_limit_exceeded_total = Counter(
            "saferoute_rate_limit_exceeded_total",
            "Total requests rejected due to client rate limits (HTTP 429)",
            ["policy"],
            registry=self.registry,
        )

        # 9. Guardrail Rejection Counter
        self.guardrail_blocks_total = Counter(
            "saferoute_guardrail_blocks_total",
            "Total requests or completions blocked by safety guardrails",
            ["stage", "detector"],
            registry=self.registry,
        )

    # -------------------------------------------------------------------------
    # Fail-safe recording helpers
    # -------------------------------------------------------------------------

    def record_http_request(
        self,
        route: str,
        status: Union[int, str],
        provider: Optional[str],
        duration_seconds: float,
    ) -> None:
        """Record overall HTTP request completion and latency."""
        try:
            b_route = normalize_route(route)
            b_status = str(status)
            b_provider = normalize_provider(provider)

            self.requests_total.labels(
                route=b_route,
                status=b_status,
                provider=b_provider,
            ).inc()

            self.request_duration_seconds.labels(
                route=b_route,
                status=b_status,
            ).observe(max(0.0, float(duration_seconds)))
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_http_request): {exc}")

    def record_provider_latency(
        self,
        provider: str,
        model: str,
        duration_seconds: float,
    ) -> None:
        """Record upstream provider call latency."""
        try:
            b_provider = normalize_provider(provider)
            b_model = normalize_model(model)
            self.provider_duration_seconds.labels(
                provider=b_provider,
                model=b_model,
            ).observe(max(0.0, float(duration_seconds)))
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_provider_latency): {exc}")

    def record_provider_error(
        self,
        provider: str,
        error_type: str,
    ) -> None:
        """Record upstream provider error or timeout."""
        try:
            b_provider = normalize_provider(provider)
            # Bound error_type
            raw_err = str(error_type).lower().strip()
            if "timeout" in raw_err:
                b_err = "timeout"
            elif "rate" in raw_err or "429" in raw_err:
                b_err = "rate_limit"
            elif "auth" in raw_err or "401" in raw_err or "403" in raw_err:
                b_err = "auth_error"
            elif "502" in raw_err or "bad_gateway" in raw_err:
                b_err = "bad_gateway"
            elif "503" in raw_err or "unavailable" in raw_err:
                b_err = "unavailable"
            elif "server" in raw_err or "500" in raw_err:
                b_err = "server_error"
            elif "connect" in raw_err or "network" in raw_err:
                b_err = "network_error"
            elif "stream" in raw_err:
                b_err = "stream_error"
            else:
                b_err = "other"

            self.provider_errors_total.labels(
                provider=b_provider,
                error_type=b_err,
            ).inc()
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_provider_error): {exc}")

    def record_cache_operation(
        self,
        cache_type: str,
        event: str,
    ) -> None:
        """Record cache operations across exact and semantic cache layers."""
        try:
            b_type = "exact" if str(cache_type).lower() == "exact" else "semantic"
            raw_event = str(event).lower().strip()
            if raw_event in ("hit", "miss", "bypass", "error", "stale_eviction"):
                b_event = raw_event
            else:
                b_event = "other"

            self.cache_operations_total.labels(
                cache_type=b_type,
                event=b_event,
            ).inc()
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_cache_operation): {exc}")

    def record_tokens(
        self,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        provider: str,
        model: str,
        source: str = "provider_reported",
    ) -> None:
        """Record input and output tokens."""
        try:
            b_provider = normalize_provider(provider)
            b_model = normalize_model(model)
            raw_src = str(source).lower().strip()
            if raw_src in ("provider_reported", "mock_estimated", "fallback_estimated"):
                b_source = raw_src
            else:
                b_source = "other"

            if input_tokens is not None and input_tokens > 0:
                self.tokens_total.labels(
                    type="input",
                    provider=b_provider,
                    model=b_model,
                    source=b_source,
                ).inc(input_tokens)

            if output_tokens is not None and output_tokens > 0:
                self.tokens_total.labels(
                    type="output",
                    provider=b_provider,
                    model=b_model,
                    source=b_source,
                ).inc(output_tokens)
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_tokens): {exc}")

    def increment_active_streams(self) -> None:
        """Increment active streaming requests gauge."""
        try:
            self.streaming_requests_active.inc()
        except Exception as exc:
            logger.debug(f"Metrics recording error (increment_active_streams): {exc}")

    def decrement_active_streams(self) -> None:
        """Decrement active streaming requests gauge."""
        try:
            self.streaming_requests_active.dec()
        except Exception as exc:
            logger.debug(f"Metrics recording error (decrement_active_streams): {exc}")

    def record_rate_limit_exceeded(self, policy: str = "fixed_window") -> None:
        """Record client rate limit rejection (HTTP 429)."""
        try:
            self.rate_limit_exceeded_total.labels(policy=policy).inc()
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_rate_limit_exceeded): {exc}")

    def record_guardrail_block(self, stage: str, detector: str) -> None:
        """Record request or output blocked by guardrail inspection."""
        try:
            b_stage = "input" if stage == "input" else "output"
            b_detector = detector if detector in ("rule", "classifier", "payload_size") else "other"
            self.guardrail_blocks_total.labels(
                stage=b_stage,
                detector=b_detector,
            ).inc()
        except Exception as exc:
            logger.debug(f"Metrics recording error (record_guardrail_block): {exc}")

    def export_metrics(self) -> bytes:
        """Export serialized Prometheus text format exposition."""
        return generate_latest(self.registry)


# Global singleton instance
_gateway_metrics: Optional[GatewayMetrics] = None


def get_metrics() -> GatewayMetrics:
    """Return the global GatewayMetrics instance."""
    global _gateway_metrics
    if _gateway_metrics is None:
        _gateway_metrics = GatewayMetrics()
    return _gateway_metrics


def reset_metrics() -> GatewayMetrics:
    """Reset the global GatewayMetrics instance with a clean registry (for testing)."""
    global _gateway_metrics
    _gateway_metrics = GatewayMetrics()
    return _gateway_metrics
