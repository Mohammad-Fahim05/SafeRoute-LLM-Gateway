"""Pydantic data models for evaluation cases, datasets, results, and benchmark metrics."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class EvaluationCaseSetup(BaseModel):
    """Configuration overrides required to establish the evaluation scenario."""
    model_config = ConfigDict(extra="forbid")

    auth_enabled: bool = True
    client_id: str = "eval_client"
    allowed_models: List[str] = Field(
        default_factory=lambda: [
            "mock-model",
            "mock-timeout",
            "mock-error",
            "mock-malformed",
            "llama3.2:1b",
            "phi3",
        ]
    )
    cache_enabled: bool = False
    cache_ttl_seconds: int = 300
    cache_namespace: str = "eval_v1"
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    rate_limit_namespace: str = "eval_v1"
    rate_limit_failure_policy: str = "fail_closed"
    guardrails_enabled: bool = False
    guardrails_input_enabled: bool = True
    guardrails_output_enabled: bool = True
    guardrails_action: str = "block"
    guardrails_max_text_length: int = 100_000
    guardrails_rules: List[Dict[str, Any]] = Field(default_factory=list)
    active_provider: str = "mock"
    provider_timeout_seconds: float = 0.5
    redis_simulate_outage: bool = False
    database_strict_mode: bool = False


class EvaluationCaseRequest(BaseModel):
    """Specification of the HTTP request to execute against the gateway."""
    model_config = ConfigDict(extra="forbid")

    endpoint: str = "/v1/chat/completions"
    method: str = "POST"
    auth: str = "valid"  # Options: "valid", "invalid", "revoked", "none", "custom"
    custom_auth_header: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Dict[str, Any] = Field(default_factory=dict)


class EvaluationCaseExpected(BaseModel):
    """Expected outcome assertions for the evaluation scenario."""
    model_config = ConfigDict(extra="forbid")

    status_code: int = 200
    error_code: Optional[str] = None
    error_type: Optional[str] = None
    cache_header: Optional[str] = None  # Expected X-Cache header value (HIT, MISS, DISABLED)
    has_choices: Optional[bool] = None
    usage_present: Optional[bool] = None
    is_mock_estimate: Optional[bool] = None
    expect_cost_null: Optional[bool] = None
    rate_limit_remaining: Optional[int] = None


class EvaluationCase(BaseModel):
    """Definition of an individual deterministic evaluation test case."""
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    description: str
    scenario_type: str = "single_request"  # "single_request", "sequential_cache_hit", "rate_limit_burst", "redis_outage"
    requires_live: bool = False
    setup: EvaluationCaseSetup = Field(default_factory=EvaluationCaseSetup)
    request: EvaluationCaseRequest = Field(default_factory=EvaluationCaseRequest)
    expected: EvaluationCaseExpected = Field(default_factory=EvaluationCaseExpected)


class EvaluationDataset(BaseModel):
    """Versioned collection of deterministic evaluation test cases."""
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    version: str
    description: str
    cases: List[EvaluationCase]


class CaseExecutionResult(BaseModel):
    """Result of evaluating a single evaluation case."""
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    description: str
    status: str  # "passed", "failed", "skipped", "errored"
    duration_ms: float
    expected_status: int
    actual_status: Optional[int] = None
    expected_error_code: Optional[str] = None
    actual_error_code: Optional[str] = None
    expected_cache_header: Optional[str] = None
    actual_cache_header: Optional[str] = None
    failure_reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class EvaluationSummary(BaseModel):
    """Aggregated outcome metrics across all evaluated cases."""
    model_config = ConfigDict(extra="forbid")

    total_cases: int
    passed: int
    failed: int
    skipped: int
    errored: int
    executed_cases: int
    pass_rate_executed_pct: float
    completion_rate_all_pct: float
    total_duration_ms: float
    pass_rate_pct: float  # Backwards-compatible alias for pass_rate_executed_pct


class BenchmarkMetrics(BaseModel):
    """High-precision latency and throughput statistics for a benchmark scenario."""
    model_config = ConfigDict(extra="forbid")

    sample_size: int
    success_count: int
    failure_count: int
    cache_hit_count: int = 0
    cache_miss_count: int = 0
    cache_hit_ratio: float = 0.0
    mean_latency_ms: float
    p50_latency_ms: float
    median_latency_ms: Optional[float] = None
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    throughput_rps: float
    provider_calls_count: Optional[int] = None
    cold_latency_ms: Optional[float] = None
    total_prompt_tokens: Optional[int] = None
    total_completion_tokens: Optional[int] = None
    total_cost: Optional[float] = None


class BenchmarkScenarioResult(BaseModel):
    """Summary of a specific performance benchmark scenario."""
    model_config = ConfigDict(extra="forbid")

    scenario_name: str
    description: str
    metrics: BenchmarkMetrics
    notes: Optional[str] = None


class EvaluationReport(BaseModel):
    """Comprehensive, machine-readable report of an evaluation run."""
    model_config = ConfigDict(extra="forbid")

    run_id: str
    timestamp_iso: str
    dataset_id: str
    dataset_version: str
    app_version: str
    git_commit: Optional[str] = None
    environment: str
    summary: EvaluationSummary
    case_results: List[CaseExecutionResult]
    benchmarks: Optional[List[BenchmarkScenarioResult]] = None
    live_services_used: bool = False
    system_info: Dict[str, Any] = Field(default_factory=dict)
