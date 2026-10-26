"""Reporting utilities for serializing evaluation results to JSON and Markdown."""

import json
from pathlib import Path
from typing import Union

from app.evaluation.models import EvaluationReport


def save_report_json(report: EvaluationReport, output_dir: Union[str, Path]) -> Path:
    """Save an EvaluationReport as a formatted JSON document.

    Ensures parent directories exist. Never logs secrets or raw prompts.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{report.run_id}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    return file_path


def generate_markdown_summary(report: EvaluationReport) -> str:
    """Generate a clean, structured Markdown summary of evaluation results."""
    s = report.summary
    status_icon = "✅" if s.failed == 0 and s.errored == 0 else "❌"

    lines = [
        f"# SafeRoute LLM Gateway — Evaluation Report",
        "",
        f"**Run ID**: `{report.run_id}`  ",
        f"**Timestamp**: `{report.timestamp_iso}`  ",
        f"**Dataset**: `{report.dataset_id}` (v{report.dataset_version})  ",
        f"**App Version**: `{report.app_version}`  ",
        f"**Live External Services**: `{'Yes' if report.live_services_used else 'No (Offline Mock Doubles)'}`  ",
        "",
        "## Summary",
        "",
        f"| Metric | Value | Formula / Definition |",
        f"| :--- | :--- | :--- |",
        f"| **Overall Result** | {status_icon} **{s.pass_rate_executed_pct}% Pass Rate** | Based on executed cases |",
        f"| **Total Cases** | {s.total_cases} | Total cases in evaluation dataset |",
        f"| **Executed Cases** | {s.executed_cases} | `passed + failed + errored` |",
        f"| **Passed** | {s.passed} | Cases meeting all expected outcomes |",
        f"| **Failed** | {s.failed} | Cases with outcome discrepancies |",
        f"| **Skipped** | {s.skipped} | Cases requiring unavailable live services |",
        f"| **Errored** | {s.errored} | Unexpected harness or execution errors |",
        f"| **Pass Rate (Executed)** | **{s.pass_rate_executed_pct}%** | `(passed / executed_cases) * 100` |",
        f"| **Completion Rate (All)** | **{s.completion_rate_all_pct}%** | `(passed / total_cases) * 100` |",
        f"| **Total Duration** | {s.total_duration_ms} ms | Monotonic execution time |",
        "",
        "## Evaluation Case Details",
        "",
        "| Case ID | Category | Status | Expected | Actual | Duration | Reason / Notes |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for c in report.case_results:
        icon = {
            "passed": "✅ PASS",
            "failed": "❌ FAIL",
            "skipped": "⚠️ SKIP",
            "errored": "💥 ERROR",
        }.get(c.status, c.status.upper())

        exp = f"HTTP {c.expected_status}"
        if c.expected_error_code:
            exp += f" ({c.expected_error_code})"
        if c.expected_cache_header:
            exp += f" [{c.expected_cache_header}]"

        act = f"HTTP {c.actual_status}" if c.actual_status is not None else "-"
        if c.actual_error_code:
            act += f" ({c.actual_error_code})"
        if c.actual_cache_header:
            act += f" [{c.actual_cache_header}]"

        reason = c.failure_reason or c.description
        # Truncate reason if too long
        if len(reason) > 60:
            reason = reason[:57] + "..."

        lines.append(
            f"| `{c.case_id}` | `{c.category}` | {icon} | {exp} | {act} | {c.duration_ms}ms | {reason} |"
        )

    if report.benchmarks:
        lines.extend([
            "",
            "## Performance Micro-Benchmarks",
            "",
            "| Scenario | Samples | Provider Calls | Hit Ratio | Mean (ms) | Median (ms) | p95 (ms) | p99 (ms) | Throughput (rps) |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])

        for b in report.benchmarks:
            m = b.metrics
            hit_ratio_str = f"{m.cache_hit_ratio * 100:.1f}%" if (m.cache_hit_count + m.cache_miss_count) > 0 else "N/A"
            prov_str = str(m.provider_calls_count) if m.provider_calls_count is not None else "N/A"
            med_val = m.median_latency_ms if m.median_latency_ms is not None else m.p50_latency_ms
            lines.append(
                f"| **{b.scenario_name}** | {m.sample_size} | {prov_str} | {hit_ratio_str} | {m.mean_latency_ms} | {med_val} | {m.p95_latency_ms} | {m.p99_latency_ms} | {m.throughput_rps} |"
            )

        lines.extend([
            "",
            "> [!NOTE]",
            "> **Benchmarking Methodology Caution**: Small local samples are indicative rather than statistically conclusive. Durations reflect local execution with MockProvider and in-memory Redis doubles.",
        ])

    lines.append("")
    return "\n".join(lines)


def save_report_markdown(report: EvaluationReport, output_dir: Union[str, Path]) -> Path:
    """Save human-readable Markdown summary of an evaluation run."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{report.run_id}.md"

    md_content = generate_markdown_summary(report)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return file_path
