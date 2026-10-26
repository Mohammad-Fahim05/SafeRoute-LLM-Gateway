"""Dataset loading and validation utilities for evaluation test suites."""

import json
from pathlib import Path
from typing import Set, Union
from pydantic import ValidationError

from app.evaluation.models import EvaluationDataset


class DatasetValidationError(Exception):
    """Raised when an evaluation dataset fails validation."""
    pass


def load_dataset_from_dict(data: dict) -> EvaluationDataset:
    """Validate and instantiate an EvaluationDataset from a dictionary.

    Enforces unique case IDs and strict field requirements.
    """
    if not isinstance(data, dict):
        raise DatasetValidationError("Dataset root must be a JSON object / dictionary.")

    try:
        dataset = EvaluationDataset.model_validate(data)
    except ValidationError as exc:
        raise DatasetValidationError(f"Invalid dataset schema: {exc}") from exc

    # Enforce uniqueness of case_id
    seen_ids: Set[str] = set()
    for case in dataset.cases:
        if case.case_id in seen_ids:
            raise DatasetValidationError(
                f"Duplicate case_id found in dataset: '{case.case_id}'. Case IDs must be unique."
            )
        seen_ids.add(case.case_id)

    return dataset


def load_dataset_from_file(file_path: Union[str, Path]) -> EvaluationDataset:
    """Read and validate an evaluation dataset from a JSON file."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Evaluation dataset file not found at: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"Malformed JSON in dataset file '{path}': {exc}") from exc
    except Exception as exc:
        raise DatasetValidationError(f"Failed to read dataset file '{path}': {exc}") from exc

    return load_dataset_from_dict(data)
