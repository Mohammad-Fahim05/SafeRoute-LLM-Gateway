"""Benchmark evaluation script for SafeRoute Phase 9.5 Semantic Safety Classification."""

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List

# Ensure gateway root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.schemas import ChatMessage
from app.config import Settings
from app.guardrails.classifier import (
    DeterministicMockSafetyClassifier,
    LocalSemanticSafetyClassifier,
)
from app.guardrails.safety_models import SafetyAction


async def evaluate_suite(
    suite_path: str,
    provider: str = "local",
    timeout_seconds: float = 1.0,
) -> Dict[str, Any]:
    with open(suite_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases", [])
    print(f"\nEvaluating {len(cases)} safety classification cases (provider={provider})...\n")

    settings = Settings(
        app_env="test",
        safety_classifier_enabled=True,
        safety_classifier_provider=provider,
        safety_classifier_timeout_seconds=timeout_seconds,
        safety_classifier_failure_policy="fail_closed",
        safety_classifier_threshold_injection=0.80,
        safety_classifier_threshold_hate=0.80,
        safety_classifier_threshold_toxicity=0.80,
        safety_classifier_threshold_pii=0.75,
        safety_classifier_action_injection="block",
        safety_classifier_action_hate="block",
        safety_classifier_action_toxicity="block",
        safety_classifier_action_pii="redact",
        safety_classifier_inspect_output=True,
    )

    t0 = time.perf_counter()
    if provider == "mock":
        classifier = DeterministicMockSafetyClassifier()
    else:
        classifier = LocalSemanticSafetyClassifier()
        # Warmup model loading
        await classifier._ensure_loaded()
    load_time_ms = round((time.perf_counter() - t0) * 1000, 2)

    results: List[Dict[str, Any]] = []
    latencies: List[float] = []

    correct_count = 0
    false_positives = 0
    false_negatives = 0

    for idx, case in enumerate(cases, 1):
        cid = case["id"]
        category = case["category"]
        exp_action = case["expected_action"]
        prompt = case["prompt"]

        msg = ChatMessage(role="user", content=prompt)
        start = time.perf_counter()
        res = await classifier.classify_input([msg], settings)
        dur = round((time.perf_counter() - start) * 1000, 2)
        latencies.append(dur)

        obs_action = res.primary_action

        # Check correctness
        is_correct = (obs_action == exp_action)
        outcome_label = "CORRECT"

        if not is_correct:
            if exp_action == "allow" and obs_action == "block":
                false_positives += 1
                outcome_label = "FALSE POSITIVE (OVER-BLOCKED)"
            elif exp_action in ("block", "redact") and obs_action == "allow":
                false_negatives += 1
                outcome_label = "FALSE NEGATIVE (UNDER-BLOCKED)"
            else:
                outcome_label = f"MISMATCH ({exp_action} vs {obs_action})"
        else:
            correct_count += 1

        print(
            f"[{idx:02d}/{len(cases):02d}] {cid:<34} "
            f"Cat: {category:<17} "
            f"Expected: {exp_action:<7} "
            f"Observed: {obs_action:<7} "
            f"Score: {res.primary_score:.4f}  "
            f"Lat: {dur:6.2f}ms  -> {outcome_label}"
        )

        results.append({
            "id": cid,
            "category": category,
            "prompt": prompt,
            "expected_action": exp_action,
            "observed_action": obs_action,
            "primary_category": res.primary_category,
            "primary_score": res.primary_score,
            "passed": res.passed,
            "status": res.status,
            "is_correct": is_correct,
            "latency_ms": dur,
            "notes": case.get("notes", ""),
        })

    accuracy = round((correct_count / len(cases)) * 100, 2) if cases else 0.0
    sorted_lats = sorted(latencies) if latencies else [0.0]
    mean_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    p50_lat = round(sorted_lats[int(len(sorted_lats) * 0.50)], 2)
    p95_lat = round(sorted_lats[min(int(len(sorted_lats) * 0.95), len(sorted_lats) - 1)], 2)
    min_lat = round(min(latencies), 2) if latencies else 0.0
    max_lat = round(max(latencies), 2) if latencies else 0.0

    # Per-category metrics
    category_stats: Dict[str, Dict[str, Any]] = {}
    for r in results:
        cat = r["category"]
        if cat not in category_stats:
            category_stats[cat] = {
                "total": 0,
                "correct": 0,
                "false_positives": 0,
                "false_negatives": 0,
                "latencies": [],
            }
        category_stats[cat]["total"] += 1
        category_stats[cat]["latencies"].append(r["latency_ms"])
        if r["is_correct"]:
            category_stats[cat]["correct"] += 1
        else:
            if r["expected_action"] == "allow" and r["observed_action"] == "block":
                category_stats[cat]["false_positives"] += 1
            elif r["expected_action"] in ("block", "redact") and r["observed_action"] == "allow":
                category_stats[cat]["false_negatives"] += 1

    for cat, stats in category_stats.items():
        stats["accuracy_pct"] = round((stats["correct"] / stats["total"]) * 100, 2) if stats["total"] else 0.0
        stats["mean_lat_ms"] = round(sum(stats["latencies"]) / len(stats["latencies"]), 2) if stats["latencies"] else 0.0
        # Precision and Recall
        tp = stats["correct"] if cat not in ("benign", "borderline") else 0
        fp = stats["false_positives"]
        fn = stats["false_negatives"]
        stats["precision"] = round(tp / (tp + fp), 4) if (tp + fp) > 0 else (1.0 if fp == 0 else 0.0)
        stats["recall"] = round(tp / (tp + fn), 4) if (tp + fn) > 0 else (1.0 if fn == 0 else 0.0)

    summary = {
        "suite_version": data.get("version", "1.1.0"),
        "provider": provider,
        "model_load_time_ms": load_time_ms,
        "total_cases": len(cases),
        "correct": correct_count,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "accuracy_pct": accuracy,
        "latency_stats_ms": {
            "mean": mean_lat,
            "p50": p50_lat,
            "p95": p95_lat,
            "min": min_lat,
            "max": max_lat,
        },
        "category_stats": category_stats,
        "results": results,
    }

    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "evaluation_results"))
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "safety_classification_benchmark.json")
    md_path = os.path.join(out_dir, "safety_classification_benchmark.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# SafeRoute Phase 9.5 — Safety Classification Benchmark Report\n\n")
        f.write(f"- **Evaluated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
        f.write(f"- **Provider**: `{provider}`\n")
        f.write(f"- **Model Initialization Latency**: `{load_time_ms} ms`\n")
        f.write(f"- **Total Test Cases**: `{len(cases)}`\n")
        f.write(f"- **Overall Accuracy**: `{accuracy}%` ({correct_count}/{len(cases)})\n")
        f.write(f"- **False Positives (FP)**: `{false_positives}`\n")
        f.write(f"- **False Negatives (FN)**: `{false_negatives}`\n")
        f.write(f"- **Mean Classification Latency**: `{mean_lat} ms`\n")
        f.write(f"- **p50 Classification Latency**: `{p50_lat} ms`\n")
        f.write(f"- **p95 Classification Latency**: `{p95_lat} ms`\n\n")

        f.write("## Per-Category Evaluation Breakdown\n\n")
        f.write("| Category | Total | Correct | FP | FN | Accuracy | Mean Latency (ms) |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for cat, st in category_stats.items():
            f.write(
                f"| `{cat}` | {st['total']} | {st['correct']} | {st['false_positives']} | "
                f"{st['false_negatives']} | {st['accuracy_pct']}% | {st['mean_lat_ms']} ms |\n"
            )
        f.write("\n## Detailed Case Results\n\n")
        f.write("| ID | Category | Expected Action | Observed Action | Score | Latency (ms) | Result |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for r in results:
            verdict = "PASS" if r["is_correct"] else "FAIL"
            f.write(
                f"| `{r['id']}` | `{r['category']}` | `{r['expected_action']}` | "
                f"`{r['observed_action']}` | `{r['primary_score']:.4f}` | "
                f"`{r['latency_ms']:.2f}` | **{verdict}** |\n"
            )

    print("\n" + "=" * 76)
    print("Safety Classification Benchmark Summary:")
    print(f"  Total Cases Evaluated   : {len(cases)}")
    print(f"  Accuracy                : {accuracy}% ({correct_count}/{len(cases)})")
    print(f"  False Positives (FP)    : {false_positives} (benign over-blocked)")
    print(f"  False Negatives (FN)    : {false_negatives} (risk under-blocked)")
    print(f"  Model Load Latency      : {load_time_ms} ms")
    print(f"  Inference Latency       : mean={mean_lat}ms, p50={p50_lat}ms, p95={p95_lat}ms, min={min_lat}ms, max={max_lat}ms")
    print("\nPer-Category Breakdown:")
    for cat, st in category_stats.items():
        print(f"  - {cat:<20}: {st['correct']}/{st['total']} ({st['accuracy_pct']}%)  FP={st['false_positives']} FN={st['false_negatives']}  mean_lat={st['mean_lat_ms']}ms")
    print(f"\n  Reports Generated       : {json_path}")
    print(f"                            {md_path}")
    print("=" * 76 + "\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Benchmark SafeRoute Semantic Safety Classification")
    parser.add_argument("--provider", default="local", choices=["local", "mock"])
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--allow-limitations", action="store_true", help="Do not exit with 1 on known test limitations")
    args = parser.parse_args()

    suite_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "datasets", "evaluation", "safety_classification_suite.json")
    )
    summary = asyncio.run(evaluate_suite(suite_path, provider=args.provider, timeout_seconds=args.timeout))
    if not args.allow_limitations:
        if summary["false_positives"] > 0 or summary["false_negatives"] > 0:
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
