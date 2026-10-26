"""Guardrail engine package providing deterministic input and output content filtering."""

from typing import Any, Optional
from fastapi import Depends
from app.config import Settings, get_settings
from app.guardrails.classifier import (
    BaseSafetyClassifier,
    DeterministicMockSafetyClassifier,
    LocalSemanticSafetyClassifier,
    get_safety_classifier,
)
from app.guardrails.engine import GuardrailEngine
from app.guardrails.models import GuardrailResult, GuardrailRule
from app.guardrails.pii import PIIScanner, pii_scanner
from app.guardrails.safety_models import (
    CategoryEvaluation,
    SafetyAction,
    SafetyClassificationResult,
    SafetyClassificationStatus,
    SafetyRiskCategory,
)

_guardrail_instance: Optional[GuardrailEngine] = None


def get_guardrail_engine(settings: Any = Depends(get_settings)) -> GuardrailEngine:
    """Dependency provider returning singleton GuardrailEngine instance."""
    actual_settings = settings if isinstance(settings, Settings) else get_settings()
    global _guardrail_instance
    if _guardrail_instance is None or _guardrail_instance.settings != actual_settings:
        _guardrail_instance = GuardrailEngine(settings=actual_settings)
    return _guardrail_instance


__all__ = [
    "GuardrailEngine",
    "GuardrailRule",
    "GuardrailResult",
    "get_guardrail_engine",
    "BaseSafetyClassifier",
    "LocalSemanticSafetyClassifier",
    "DeterministicMockSafetyClassifier",
    "get_safety_classifier",
    "PIIScanner",
    "pii_scanner",
    "SafetyRiskCategory",
    "SafetyAction",
    "SafetyClassificationStatus",
    "CategoryEvaluation",
    "SafetyClassificationResult",
]
