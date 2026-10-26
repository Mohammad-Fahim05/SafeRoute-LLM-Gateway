"""Deterministic rule-based inspection engine for chat completion inputs and outputs."""

from typing import List, Optional, Union
from app.api.schemas import ChatMessage
from app.config import Settings
from app.core.logging import logger
from app.guardrails.models import GuardrailResult, GuardrailRule


class GuardrailEngine:
    """Independent, deterministic evaluation engine inspecting text against configured guardrail rules."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rules: List[GuardrailRule] = [
            GuardrailRule.from_dict(r) for r in settings.guardrails_rules
        ]

    def inspect_input(self, messages: List[Union[ChatMessage, dict]]) -> GuardrailResult:
        """Evaluate incoming conversation messages against input-eligible rules.

        Preserves message order and checks each user/system/assistant turn.
        Never logs prompt contents or exposes internal regex details.
        """
        if not self.settings.guardrails_enabled or not self.settings.guardrails_input_enabled:
            return GuardrailResult(
                passed=True,
                action="allow",
                stage="none",
                reason_code="disabled",
            )

        input_rules = [r for r in self.rules if r.stage in ("input", "both")]
        if not input_rules:
            return GuardrailResult(
                passed=True,
                action="allow",
                stage="input",
                reason_code="passed",
            )

        for idx, msg in enumerate(messages):
            # Extract content from ChatMessage object or raw dictionary
            content = msg.content if isinstance(msg, ChatMessage) else msg.get("content", "")
            text_blocks: List[str] = [content] if content else []
            tool_calls = msg.tool_calls if isinstance(msg, ChatMessage) else (msg.get("tool_calls") if isinstance(msg, dict) else None)
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.function if hasattr(tc, "function") else (tc.get("function", {}) if isinstance(tc, dict) else {})
                    args = fn.arguments if hasattr(fn, "arguments") else (fn.get("arguments", "") if isinstance(fn, dict) else "")
                    if args:
                        text_blocks.append(str(args))

            if not text_blocks:
                continue

            for block_text in text_blocks:
                if len(block_text) > self.settings.guardrails_max_text_length:
                    logger.warning(
                        f"Input guardrail blocked request: message at index {idx} exceeds max text length {self.settings.guardrails_max_text_length}",
                        extra={
                            "extra_data": {
                                "stage": "input",
                                "message_index": idx,
                                "reason_code": "processing_limit_exceeded",
                            }
                        },
                    )
                    return GuardrailResult(
                        passed=False,
                        action="block",
                        stage="input",
                        reason_code="processing_limit_exceeded",
                        message="Input content exceeds maximum allowed length for guardrail evaluation.",
                    )

                for rule in input_rules:
                    if self._matches(rule, block_text):
                        logger.warning(
                            f"Input guardrail blocked request: rule={rule.rule_id}",
                            extra={
                                "extra_data": {
                                    "stage": "input",
                                    "rule_id": rule.rule_id,
                                    "message_index": idx,
                                    "reason_code": "blocked_by_rule",
                                }
                            },
                        )
                        return GuardrailResult(
                            passed=False,
                            action="block",
                            matched_rule_id=rule.rule_id,
                            stage="input",
                            reason_code="blocked_by_rule",
                            message="Request content was blocked by input safety guardrails.",
                        )

        return GuardrailResult(
            passed=True,
            action="allow",
            stage="input",
            reason_code="passed",
        )

    def inspect_output(self, text: Optional[str]) -> GuardrailResult:
        """Evaluate provider completion text against output-eligible rules.

        Ensures prohibited or policy-violating text is intercepted before
        being cached or delivered to the client.
        """
        if not self.settings.guardrails_enabled or not self.settings.guardrails_output_enabled:
            return GuardrailResult(
                passed=True,
                action="allow",
                stage="none",
                reason_code="disabled",
            )

        if not text:
            return GuardrailResult(
                passed=True,
                action="allow",
                stage="output",
                reason_code="passed",
            )

        if len(text) > self.settings.guardrails_max_text_length:
            logger.warning(
                f"Output guardrail blocked response: exceeds max text length {self.settings.guardrails_max_text_length}",
                extra={
                    "extra_data": {
                        "stage": "output",
                        "reason_code": "processing_limit_exceeded",
                    }
                },
            )
            return GuardrailResult(
                passed=False,
                action="block",
                stage="output",
                reason_code="processing_limit_exceeded",
                message="Output content exceeds maximum allowed length for guardrail evaluation.",
            )

        output_rules = [r for r in self.rules if r.stage in ("output", "both")]
        for rule in output_rules:
            if self._matches(rule, text):
                logger.warning(
                    f"Output guardrail blocked response: rule={rule.rule_id}",
                    extra={
                        "extra_data": {
                            "stage": "output",
                            "rule_id": rule.rule_id,
                            "reason_code": "blocked_by_rule",
                        }
                    },
                )
                return GuardrailResult(
                    passed=False,
                    action="block",
                    matched_rule_id=rule.rule_id,
                    stage="output",
                    reason_code="blocked_by_rule",
                    message="Provider response was blocked by output safety guardrails.",
                )

        return GuardrailResult(
            passed=True,
            action="allow",
            stage="output",
            reason_code="passed",
        )

    @staticmethod
    def _matches(rule: GuardrailRule, content: str) -> bool:
        """Check whether the given content matches the configured rule."""
        if rule.match_type == "contains":
            if rule.case_sensitive:
                return rule.pattern in content
            return rule.pattern.lower() in content.lower()

        if rule.compiled_pattern is not None:
            return bool(rule.compiled_pattern.search(content))

        return False
