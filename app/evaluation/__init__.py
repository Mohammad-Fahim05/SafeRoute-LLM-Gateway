"""Evaluation and benchmarking module for SafeRoute LLM Gateway."""

from app.evaluation.models import (
    BenchmarkMetrics,
    BenchmarkScenarioResult,
    CaseExecutionResult,
    EvaluationCase,
    EvaluationCaseExpected,
    EvaluationCaseRequest,
    EvaluationCaseSetup,
    EvaluationDataset,
    EvaluationReport,
    EvaluationSummary,
)
from app.evaluation.loader import load_dataset_from_file, load_dataset_from_dict
from app.evaluation.runner import EvaluationRunner
from app.evaluation.benchmarker import PerformanceBenchmarker
from app.evaluation.reporter import save_report_json, save_report_markdown, generate_markdown_summary

__all__ = [
    "BenchmarkMetrics",
    "BenchmarkScenarioResult",
    "CaseExecutionResult",
    "EvaluationCase",
    "EvaluationCaseExpected",
    "EvaluationCaseRequest",
    "EvaluationCaseSetup",
    "EvaluationDataset",
    "EvaluationReport",
    "EvaluationSummary",
    "load_dataset_from_file",
    "load_dataset_from_dict",
    "EvaluationRunner",
    "PerformanceBenchmarker",
    "save_report_json",
    "save_report_markdown",
    "generate_markdown_summary",
]
