"""Unit tests for the evaluation and benchmarking framework components."""

import json
from pathlib import Path
import pytest

from app.evaluation.benchmarker import calculate_percentiles
from app.evaluation.loader import (
    DatasetValidationError,
    load_dataset_from_dict,
    load_dataset_from_file,
)
from app.evaluation.models import (
    CaseExecutionResult,
    EvaluationCase,
    EvaluationCaseExpected,
    EvaluationCaseRequest,
    EvaluationCaseSetup,
    EvaluationDataset,
    EvaluationReport,
    EvaluationSummary,
)
from app.evaluation.reporter import generate_markdown_summary, save_report_json


def test_load_dataset_from_valid_dict():
    """Verify standard valid dataset dictionary parses into EvaluationDataset."""
    data = {
        "dataset_id": "test_suite_v1",
        "version": "1.0.0",
        "description": "Test evaluation suite",
        "cases": [
            {
                "case_id": "c1",
                "category": "test",
                "description": "Test case 1",
                "scenario_type": "single_request",
                "setup": {"auth_enabled": True},
                "request": {"endpoint": "/v1/chat/completions", "method": "POST", "body": {}},
                "expected": {"status_code": 200},
            }
        ],
    }
    ds = load_dataset_from_dict(data)
    assert ds.dataset_id == "test_suite_v1"
    assert len(ds.cases) == 1
    assert ds.cases[0].case_id == "c1"


def test_load_dataset_rejects_non_dict_root():
    """Verify non-dictionary root raises DatasetValidationError."""
    with pytest.raises(DatasetValidationError, match="must be a JSON object"):
        load_dataset_from_dict(["invalid", "list"])  # type: ignore


def test_load_dataset_rejects_missing_required_fields():
    """Verify missing required fields triggers validation error."""
    with pytest.raises(DatasetValidationError, match="Invalid dataset schema"):
        load_dataset_from_dict({"dataset_id": "incomplete"})


def test_load_dataset_rejects_duplicate_case_ids():
    """Verify duplicate case IDs are detected and rejected."""
    data = {
        "dataset_id": "test_dups",
        "version": "1.0.0",
        "description": "Duplicate cases test",
        "cases": [
            {
                "case_id": "duplicate_id",
                "category": "cat1",
                "description": "First instance",
                "expected": {"status_code": 200},
            },
            {
                "case_id": "duplicate_id",
                "category": "cat2",
                "description": "Second instance",
                "expected": {"status_code": 400},
            },
        ],
    }
    with pytest.raises(DatasetValidationError, match="Duplicate case_id found in dataset: 'duplicate_id'"):
        load_dataset_from_dict(data)


def test_load_dataset_from_missing_file_raises_not_found(tmp_path: Path):
    """Verify FileNotFoundError is raised when file does not exist."""
    missing = tmp_path / "non_existent.json"
    with pytest.raises(FileNotFoundError):
        load_dataset_from_file(missing)


def test_calculate_percentiles_empty_list():
    """Verify empty duration list returns zeroed metrics without crashing."""
    stats = calculate_percentiles([])
    assert stats["mean"] == 0.0
    assert stats["p50"] == 0.0
    assert stats["min"] == 0.0
    assert stats["max"] == 0.0


def test_calculate_percentiles_exact_quantiles():
    """Verify mean, median, min, max, p95, p99 on a known dataset."""
    durations = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = calculate_percentiles(durations)
    assert stats["mean"] == 30.0
    assert stats["min"] == 10.0
    assert stats["max"] == 50.0
    assert stats["p50"] == 30.0
    assert stats["p95"] == 50.0
    assert stats["p99"] == 50.0


def test_calculate_percentiles_single_sample():
    """Verify single-element list calculates exact min, max, mean, median, p95, p99."""
    stats = calculate_percentiles([42.5])
    assert stats["mean"] == 42.5
    assert stats["min"] == 42.5
    assert stats["max"] == 42.5
    assert stats["p50"] == 42.5
    assert stats["median"] == 42.5
    assert stats["p95"] == 42.5
    assert stats["p99"] == 42.5


def test_calculate_percentiles_even_sample_median():
    """Verify even-sized sample calculates standard mathematical median (average of middle elements)."""
    stats = calculate_percentiles([10.0, 20.0])
    assert stats["mean"] == 15.0
    assert stats["p50"] == 15.0
    assert stats["median"] == 15.0
    assert stats["min"] == 10.0
    assert stats["max"] == 20.0
    assert stats["p95"] == 20.0
    assert stats["p99"] == 20.0


def test_calculate_percentiles_identical_samples():
    """Verify list of identical latency samples produces uniform percentiles."""
    stats = calculate_percentiles([15.0, 15.0, 15.0, 15.0])
    assert stats["mean"] == 15.0
    assert stats["p50"] == 15.0
    assert stats["median"] == 15.0
    assert stats["p95"] == 15.0
    assert stats["p99"] == 15.0


def test_evaluation_summary_percentage_formulas_and_zero_division():
    """Verify executed_cases, pass_rate_executed_pct, and completion_rate_all_pct formulas and zero-division protection."""
    # 1. Standard run with 15 total, 14 passed, 0 failed, 1 skipped, 0 errored
    s1 = EvaluationSummary(
        total_cases=15,
        passed=14,
        failed=0,
        skipped=1,
        errored=0,
        executed_cases=14,
        pass_rate_executed_pct=round((14 / 14) * 100.0, 2),
        completion_rate_all_pct=round((14 / 15) * 100.0, 2),
        pass_rate_pct=round((14 / 14) * 100.0, 2),
        total_duration_ms=500.0,
    )
    assert s1.executed_cases == 14
    assert s1.pass_rate_executed_pct == 100.0
    assert s1.completion_rate_all_pct == 93.33

    # 2. Run with failures: 15 total, 12 passed, 2 failed, 1 skipped
    s2 = EvaluationSummary(
        total_cases=15,
        passed=12,
        failed=2,
        skipped=1,
        errored=0,
        executed_cases=14,
        pass_rate_executed_pct=round((12 / 14) * 100.0, 2),
        completion_rate_all_pct=round((12 / 15) * 100.0, 2),
        pass_rate_pct=round((12 / 14) * 100.0, 2),
        total_duration_ms=600.0,
    )
    assert s2.executed_cases == 14
    assert s2.pass_rate_executed_pct == 85.71
    assert s2.completion_rate_all_pct == 80.0

    # 3. Zero executed cases protection
    s_zero = EvaluationSummary(
        total_cases=5,
        passed=0,
        failed=0,
        skipped=5,
        errored=0,
        executed_cases=0,
        pass_rate_executed_pct=0.0,
        completion_rate_all_pct=0.0,
        pass_rate_pct=0.0,
        total_duration_ms=10.0,
    )
    assert s_zero.executed_cases == 0
    assert s_zero.pass_rate_executed_pct == 0.0
    assert s_zero.completion_rate_all_pct == 0.0


def test_report_serialization_and_secret_redaction(tmp_path: Path):
    """Verify reports do not contain API keys or auth secrets."""
    summary = EvaluationSummary(
        total_cases=1,
        passed=1,
        failed=0,
        skipped=0,
        errored=0,
        executed_cases=1,
        pass_rate_executed_pct=100.0,
        completion_rate_all_pct=100.0,
        pass_rate_pct=100.0,
        total_duration_ms=45.2,
    )
    case_res = CaseExecutionResult(
        case_id="eval_01",
        category="security",
        description="Verify redaction",
        status="passed",
        duration_ms=45.2,
        expected_status=200,
        actual_status=200,
        details={"status": "ok"},
    )
    report = EvaluationReport(
        run_id="eval_test_redaction",
        timestamp_iso="2026-10-24T20:00:00Z",
        dataset_id="test_ds",
        dataset_version="1.0.0",
        app_version="0.1.0",
        environment="test",
        summary=summary,
        case_results=[case_res],
    )

    json_path = save_report_json(report, tmp_path)
    with open(json_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "gw_test_" not in content
    assert "SECRET" not in content
    assert "eval_test_redaction" in content

    md_content = generate_markdown_summary(report)
    assert "gw_test_" not in md_content
    assert "100.0% Pass Rate" in md_content
