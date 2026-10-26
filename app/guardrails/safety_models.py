"""Data models and typed results for semantic safety classification and moderation."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SafetyRiskCategory(str, Enum):
    """Supported risk categories for semantic safety classification."""

    PROMPT_INJECTION = "prompt_injection"
    HATE_SPEECH = "hate_speech"
    SEVERE_TOXICITY = "severe_toxicity"
    PII = "pii"


class SafetyAction(str, Enum):
    """Enforceable policy actions upon risk detection."""

    ALLOW = "allow"
    BLOCK = "block"
    FLAG_AND_FORWARD = "flag_and_forward"
    REDACT = "redact"


class SafetyClassificationStatus(str, Enum):
    """Overall outcome status of a safety classification pass."""

    CLEAN = "clean"
    FLAGGED = "flagged"
    BLOCKED = "blocked"
    REDACTED = "redacted"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CategoryEvaluation:
    """Individual assessment for a specific safety risk category."""

    category: str
    detected: bool
    score: float
    action: str
    reason: str
    redacted_text: Optional[str] = None


@dataclass(frozen=True)
class SafetyClassificationResult:
    """Complete, typed result returned by the semantic safety classification layer.

    Contains aggregate and per-category evaluation without exposing raw prompts
    or sensitive user data in logs or operational telemetry.
    """

    passed: bool
    status: str
    primary_category: Optional[str] = None
    primary_score: float = 0.0
    primary_action: str = "allow"
    reason: str = "clean"
    category_evaluations: Dict[str, CategoryEvaluation] = field(default_factory=dict)
    redacted_messages: Optional[List[Any]] = None
    duration_ms: float = 0.0

    @property
    def should_block(self) -> bool:
        """True if any evaluated category demands blocking the request."""
        return self.primary_action == SafetyAction.BLOCK.value or not self.passed

    @property
    def has_flagged_category(self) -> bool:
        """True if primary action is flag_and_forward or any individual category was flagged."""
        return (
            self.primary_action == SafetyAction.FLAG_AND_FORWARD.value
            or any(ev.action == SafetyAction.FLAG_AND_FORWARD.value for ev in self.category_evaluations.values())
        )

    @property
    def is_flagged(self) -> bool:
        """True if the request is flagged for internal monitoring but allowed forward."""
        return self.has_flagged_category

    @property
    def is_redacted(self) -> bool:
        """True if sensitive content was sanitized in-place."""
        return (
            self.status == SafetyClassificationStatus.REDACTED.value
            or self.primary_action == SafetyAction.REDACT.value
            or any(ev.action == SafetyAction.REDACT.value for ev in self.category_evaluations.values())
        )
