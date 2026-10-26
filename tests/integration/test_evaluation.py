"""Integration tests for the evaluation runner, benchmarking, and CLI harness."""

import subprocess
import sys
from pathlib import Path
import pytest

from app.evaluation.benchmarker import PerformanceBenchmarker
from app.evaluation.loader import load_dataset_from_dict, load_dataset_from_file
from app.evaluation.reporter import save_report_json, save_report_markdown
from app.evaluation.runner import EvaluationRunner

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATASET_PATH = PROJECT_ROOT / "datasets" / "evaluation" / "default_suite.json"


def test_default_evaluation_suite_execution():
    """Verify standard default evaluation suite runs successfully and achieves 100% pass rate."""
    dataset = load_dataset_from_file(DEFAULT_DATASET_PATH)
    assert len(dataset.cases) >= 15

    runner = EvaluationRunner(dataset=dataset, mode="quick", live=False)
    report = runner.run()

    assert report.summary.total_cases == len(dataset.cases)
    assert report.summary.passed >= 14
    assert report.summary.failed == 0
    assert report.summary.errored == 0
    assert report.summary.skipped == 1  # eval_15_live_ollama_optional
    assert report.summary.executed_cases == 14
    assert report.summary.pass_rate_executed_pct == 100.0
    assert report.summary.completion_rate_all_pct == round((14 / len(dataset.cases)) * 100.0, 2)
    assert report.summary.pass_rate_pct == 100.0


def test_performance_benchmarker_execution():
    """Verify performance benchmarking scenarios execute and produce valid latency percentiles."""
    benchmarker = PerformanceBenchmarker(iterations=5)
    results = benchmarker.run_all()

    assert len(results) == 4
    scenario_names = [r.scenario_name for r in results]
    assert "warm_cache_hits" in scenario_names
    assert "cache_disabled_baseline" in scenario_names
    assert "guardrails_active_overhead" in scenario_names
    assert "provider_error_handling" in scenario_names

    # Warm cache test should have hit ratio >= 0.8 (1 cold miss, 5 warm hits = 5/6 = 83.3%)
    warm_res = next(r for r in results if r.scenario_name == "warm_cache_hits")
    assert warm_res.metrics.cache_hit_ratio >= 0.8
    assert warm_res.metrics.mean_latency_ms > 0.0
    assert warm_res.metrics.p50_latency_ms > 0.0
    assert warm_res.metrics.median_latency_ms is not None
    assert warm_res.metrics.cold_latency_ms is not None
    assert warm_res.metrics.provider_calls_count == 1  # Exactly 1 provider invocation for cold priming
    assert warm_res.metrics.throughput_rps > 0.0

    # Cache disabled scenario should invoke provider for each iteration
    nocache_res = next(r for r in results if r.scenario_name == "cache_disabled_baseline")
    assert nocache_res.metrics.provider_calls_count == 5


def test_evaluation_runner_detects_deliberate_failure():
    """Verify runner marks failed cases accurately when actual status differs from expected."""
    fail_data = {
        "dataset_id": "test_failure_detection",
        "version": "1.0.0",
        "description": "Test failure detection",
        "cases": [
            {
                "case_id": "failing_case",
                "category": "failure_test",
                "description": "Expects 200 but sends invalid key returning 401",
                "scenario_type": "single_request",
                "setup": {"auth_enabled": True},
                "request": {
                    "endpoint": "/v1/chat/completions",
                    "method": "POST",
                    "auth": "invalid",
                    "body": {"model": "mock-model", "messages": [{"role": "user", "content": "Hi"}]},
                },
                "expected": {
                    "status_code": 200  # Deliberately mismatched: actual is 401!
                },
            }
        ],
    }
    dataset = load_dataset_from_dict(fail_data)
    runner = EvaluationRunner(dataset=dataset, mode="quick", live=False)
    report = runner.run()

    assert report.summary.total_cases == 1
    assert report.summary.executed_cases == 1
    assert report.summary.passed == 0
    assert report.summary.failed == 1
    assert report.summary.pass_rate_executed_pct == 0.0
    assert report.summary.completion_rate_all_pct == 0.0
    assert "Expected status 200, got 401" in (report.case_results[0].failure_reason or "")


def test_evaluation_cli_script_execution(tmp_path: Path):
    """Verify scripts/run_evaluation.py executes via subprocess, outputs reports, and exits with 0."""
    script_path = PROJECT_ROOT / "scripts" / "run_evaluation.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--dataset",
        str(DEFAULT_DATASET_PATH),
        "--mode",
        "quick",
        "--output-dir",
        str(tmp_path),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    assert res.returncode == 0
    assert "Pass Rate (Executed)  : 100.0%" in res.stdout
    assert "Completion Rate (All) : 93.33%" in res.stdout
    assert "Executed Cases        : 14" in res.stdout

    # Check generated report files exist on disk
    json_reports = list(tmp_path.glob("*.json"))
    md_reports = list(tmp_path.glob("*.md"))
    assert len(json_reports) == 1
    assert len(md_reports) == 1
