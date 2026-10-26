#!/usr/bin/env python3
"""SafeRoute LLM Gateway — Reproducible Evaluation and Benchmarking CLI Runner.

Executes deterministic evaluation datasets against the gateway, measures latency,
cache efficiency, guardrail effectiveness, and rate limiting, and saves structured reports.
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.benchmarker import PerformanceBenchmarker
from app.evaluation.loader import DatasetValidationError, load_dataset_from_file
from app.evaluation.reporter import save_report_json, save_report_markdown
from app.evaluation.runner import EvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run reproducible evaluation and performance benchmarks on SafeRoute LLM Gateway."
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(PROJECT_ROOT / "datasets" / "evaluation" / "default_suite.json"),
        help="Path to evaluation dataset JSON file (default: datasets/evaluation/default_suite.json).",
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="full",
        help="Evaluation mode: 'quick' (core functional cases only) or 'full' (functional cases + performance benchmarks).",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Explicitly enable performance micro-benchmarks even in quick mode.",
    )
    parser.add_argument(
        "--benchmark-iterations",
        type=int,
        default=20,
        help="Number of iterations for performance benchmark scenarios (default: 20).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable cases requiring live external services (e.g. live Ollama daemon, live Redis).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "data" / "evaluation_results"),
        help="Directory where JSON and Markdown reports will be stored (default: data/evaluation_results).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed per-case console output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset)
    output_dir = Path(args.output_dir)

    print("=" * 76)
    print("SafeRoute LLM Gateway — Evaluation & Benchmarking Harness")
    print(f"Dataset Path : {dataset_path}")
    print(f"Runner Mode  : {args.mode}")
    print(f"Live Services: {'ENABLED' if args.live else 'DISABLED (Mock doubles only)'}")
    print("=" * 76)

    # 1. Load and validate dataset
    try:
        dataset = load_dataset_from_file(dataset_path)
    except (FileNotFoundError, DatasetValidationError) as exc:
        print(f"\n[ERROR] Dataset loading failed: {exc}", file=sys.stderr)
        return 1

    print(f"Loaded dataset '{dataset.dataset_id}' (v{dataset.version}): {len(dataset.cases)} test cases.\n")

    # 2. Execute evaluation runner
    runner = EvaluationRunner(dataset=dataset, mode=args.mode, live=args.live)
    report = runner.run()

    # 3. Print per-case results
    if not args.quiet:
        print("Executing Evaluation Cases:")
        print("-" * 76)
        for c in report.case_results:
            icon = {
                "passed": "[PASS]",
                "failed": "[FAIL]",
                "skipped": "[SKIP]",
                "errored": "[ERR!]",
            }.get(c.status, f"[{c.status.upper()}]")

            status_str = f"{icon:<6} {c.case_id:<32} ({c.duration_ms:>6.2f}ms)"
            if c.failure_reason:
                status_str += f" -> {c.failure_reason}"
            print(status_str)
        print("-" * 76)

    # 4. Run benchmarks if in full mode or explicitly enabled
    should_benchmark = args.benchmark or (args.mode == "full")
    if should_benchmark:
        print(f"\nRunning Performance Micro-Benchmarks ({args.benchmark_iterations} iterations/scenario)...")
        benchmarker = PerformanceBenchmarker(iterations=args.benchmark_iterations)
        bench_results = benchmarker.run_all()
        report.benchmarks = bench_results

        print("-" * 76)
        print(f"{'Scenario':<28} {'Hit Ratio':<12} {'Mean (ms)':<10} {'p50 (ms)':<10} {'Throughput':<12}")
        print("-" * 76)
        for b in bench_results:
            m = b.metrics
            hit_ratio_str = f"{m.cache_hit_ratio * 100:.1f}%" if m.cache_hit_count > 0 else "N/A"
            print(f"{b.scenario_name:<28} {hit_ratio_str:<12} {m.mean_latency_ms:<10} {m.p50_latency_ms:<10} {f'{m.throughput_rps} rps':<12}")
        print("-" * 76)

    # 5. Save reports
    json_path = save_report_json(report, output_dir)
    md_path = save_report_markdown(report, output_dir)

    print("\n" + "=" * 76)
    print("Evaluation Summary:")
    print(f"  Total Cases           : {report.summary.total_cases}")
    print(f"  Executed Cases        : {report.summary.executed_cases}")
    print(f"  Passed                : {report.summary.passed}")
    print(f"  Failed                : {report.summary.failed}")
    print(f"  Skipped               : {report.summary.skipped}")
    print(f"  Errored               : {report.summary.errored}")
    print(f"  Pass Rate (Executed)  : {report.summary.pass_rate_executed_pct}%")
    print(f"  Completion Rate (All) : {report.summary.completion_rate_all_pct}%")
    print(f"  Duration              : {report.summary.total_duration_ms} ms")
    print("-" * 76)
    print(f"JSON Report : {json_path}")
    print(f"Markdown    : {md_path}")
    print("=" * 76)

    # Return non-zero if any required case failed or errored
    if report.summary.failed > 0 or report.summary.errored > 0:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
