"""Data models for guardrail rules, inspection requests, and evaluation results."""

from dataclasses import dataclass
import re
from typing import Optional


@dataclass(frozen=True)
class GuardrailRule:
    """Compiled, immutable guardrail rule for inspecting input prompts or output completions."""

    rule_id: str
    pattern: str
    match_type: str = "regex"  # "regex", "contains", "keyword"
    case_sensitive: bool = False
    stage: str = "both"  # "input", "output", "both"
    action: str = "block"  # currently supported: "block"
    description: Optional[str] = None
    compiled_pattern: Optional[re.Pattern] = None

    @classmethod
    def from_dict(cls, data: dict) -> "GuardrailRule":
        """Instantiate and compile a GuardrailRule from configuration dictionary."""
        rule_id = str(data["rule_id"]).strip()
        pattern = str(data["pattern"]).strip()
        match_type = str(data.get("match_type", "regex")).lower().strip()
        case_sensitive = bool(data.get("case_sensitive", False))
        stage = str(data.get("stage", "both")).lower().strip()
        action = str(data.get("action", "block")).lower().strip()
        description = data.get("description")

        flags = 0 if case_sensitive else re.IGNORECASE
        compiled: Optional[re.Pattern] = None

        if match_type == "keyword":
            compiled = re.compile(rf"\b{re.escape(pattern)}\b", flags=flags)
        elif match_type == "regex":
            compiled = re.compile(pattern, flags=flags)

        return cls(
            rule_id=rule_id,
            pattern=pattern,
            match_type=match_type,
            case_sensitive=case_sensitive,
            stage=stage,
            action=action,
            description=description,
            compiled_pattern=compiled,
        )


@dataclass(frozen=True)
class GuardrailResult:
    """Structured result returned by the guardrail evaluation engine."""

    passed: bool
    action: str = "allow"  # "allow" or "block"
    matched_rule_id: Optional[str] = None
    stage: str = "none"  # "input", "output", "none"
    reason_code: str = "passed"  # "passed", "blocked_by_rule", "processing_limit_exceeded", "disabled"
    message: Optional[str] = None
