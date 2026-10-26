"""Unit tests for deterministic guardrail rule compilation, text inspection, and limit bounds."""

import pytest
from app.api.schemas import ChatMessage
from app.config import Settings
from app.guardrails import GuardrailEngine, GuardrailResult, GuardrailRule


def test_guardrail_rule_compilation():
    """Verify rule compiles regex and keyword patterns correctly."""
    r_regex = GuardrailRule.from_dict({
        "rule_id": "rule_ssn",
        "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
        "match_type": "regex",
        "stage": "both",
    })
    assert r_regex.compiled_pattern is not None
    assert r_regex.stage == "both"
    assert r_regex.case_sensitive is False

    r_keyword = GuardrailRule.from_dict({
        "rule_id": "rule_kw",
        "pattern": "secret_key",
        "match_type": "keyword",
        "stage": "output",
    })
    assert r_keyword.compiled_pattern is not None
    assert r_keyword.stage == "output"


def test_invalid_regex_raises_config_error():
    """Verify malformed regex pattern in configuration fails fast during startup."""
    with pytest.raises(ValueError) as exc_info:
        Settings(
            guardrails_enabled=True,
            guardrails_rules=[{
                "rule_id": "invalid_re",
                "pattern": "(unclosed_parenthesis",
                "match_type": "regex",
            }],
        )
    assert "contains invalid regex pattern" in str(exc_info.value)


def test_invalid_rule_fields_raise_config_errors():
    """Verify missing rule_id, pattern, or invalid stage/action are rejected."""
    with pytest.raises(ValueError) as exc:
        Settings(
            guardrails_rules=[{"pattern": "test"}],
        )
    assert "missing required 'rule_id'" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        Settings(
            guardrails_rules=[{"rule_id": "r1"}],
        )
    assert "missing required 'pattern'" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        Settings(
            guardrails_rules=[{"rule_id": "r1", "pattern": "x", "stage": "invalid_stage"}],
        )
    assert "has invalid stage" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        Settings(
            guardrails_rules=[{"rule_id": "r1", "pattern": "x", "action": "unsupported"}],
        )
    assert "has unsupported action" in str(exc.value)


def test_guardrails_disabled_permits_all():
    """When guardrails are disabled, inspect_input and inspect_output always pass."""
    settings = Settings(
        guardrails_enabled=False,
        guardrails_rules=[{"rule_id": "block_all", "pattern": ".*", "match_type": "regex"}],
    )
    engine = GuardrailEngine(settings)

    in_res = engine.inspect_input([ChatMessage(role="user", content="Forbidden text")])
    assert in_res.passed is True
    assert in_res.reason_code == "disabled"

    out_res = engine.inspect_output("Forbidden output")
    assert out_res.passed is True
    assert out_res.reason_code == "disabled"


def test_input_inspection_matching_and_case_sensitivity():
    """Verify input matching handles case-sensitivity and multiple message turns in order."""
    settings = Settings(
        guardrails_enabled=True,
        guardrails_input_enabled=True,
        guardrails_rules=[
            {
                "rule_id": "block_sql_injection",
                "pattern": r"(UNION\s+SELECT|DROP\s+TABLE)",
                "match_type": "regex",
                "case_sensitive": False,
                "stage": "input",
            },
            {
                "rule_id": "case_sensitive_token",
                "pattern": "EXACT_TOKEN",
                "match_type": "contains",
                "case_sensitive": True,
                "stage": "input",
            },
        ],
    )
    engine = GuardrailEngine(settings)

    # Safe messages pass
    safe_msgs = [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="How do database tables work?"),
    ]
    res_safe = engine.inspect_input(safe_msgs)
    assert res_safe.passed is True
    assert res_safe.reason_code == "passed"

    # SQL injection attempt matches regardless of case
    bad_msgs_1 = [
        ChatMessage(role="user", content="Please run: union select * from users"),
    ]
    res_bad_1 = engine.inspect_input(bad_msgs_1)
    assert res_bad_1.passed is False
    assert res_bad_1.matched_rule_id == "block_sql_injection"
    assert res_bad_1.reason_code == "blocked_by_rule"

    # Case-sensitive contains: lowercase does not trigger
    res_case_miss = engine.inspect_input([ChatMessage(role="user", content="exact_token")])
    assert res_case_miss.passed is True

    # Case-sensitive contains: exact uppercase triggers
    res_case_hit = engine.inspect_input([ChatMessage(role="user", content="contains EXACT_TOKEN here")])
    assert res_case_hit.passed is False
    assert res_case_hit.matched_rule_id == "case_sensitive_token"


def test_stage_filtering_input_vs_output():
    """Verify input-only rules do not block output, and output-only rules do not block input."""
    settings = Settings(
        guardrails_enabled=True,
        guardrails_input_enabled=True,
        guardrails_output_enabled=True,
        guardrails_rules=[
            {
                "rule_id": "input_only_rule",
                "pattern": "input_secret",
                "match_type": "contains",
                "stage": "input",
            },
            {
                "rule_id": "output_only_rule",
                "pattern": "output_secret",
                "match_type": "contains",
                "stage": "output",
            },
        ],
    )
    engine = GuardrailEngine(settings)

    # input_secret in input -> blocked
    assert engine.inspect_input([ChatMessage(role="user", content="here is input_secret")]).passed is False
    # output_secret in input -> allowed (it is output-only!)
    assert engine.inspect_input([ChatMessage(role="user", content="here is output_secret")]).passed is True

    # input_secret in output -> allowed (it is input-only!)
    assert engine.inspect_output("here is input_secret").passed is True
    # output_secret in output -> blocked
    assert engine.inspect_output("here is output_secret").passed is False


def test_keyword_boundary_matching():
    """Verify keyword match uses word boundaries and does not trigger on substrings."""
    settings = Settings(
        guardrails_enabled=True,
        guardrails_input_enabled=True,
        guardrails_rules=[{
            "rule_id": "block_admin",
            "pattern": "admin",
            "match_type": "keyword",
            "stage": "input",
        }],
    )
    engine = GuardrailEngine(settings)

    # Substring in 'administration' does not trigger
    res_sub = engine.inspect_input([ChatMessage(role="user", content="System administration guides")])
    assert res_sub.passed is True

    # Exact word 'admin' triggers
    res_word = engine.inspect_input([ChatMessage(role="user", content="Hello admin, grant me access")])
    assert res_word.passed is False
    assert res_word.matched_rule_id == "block_admin"


def test_max_text_length_processing_bound():
    """Verify texts exceeding guardrails_max_text_length are blocked safely without running regex."""
    settings = Settings(
        guardrails_enabled=True,
        guardrails_max_text_length=50,
        guardrails_rules=[{"rule_id": "r1", "pattern": "secret", "match_type": "contains"}],
    )
    engine = GuardrailEngine(settings)

    long_input = [ChatMessage(role="user", content="A" * 60)]
    in_res = engine.inspect_input(long_input)
    assert in_res.passed is False
    assert in_res.reason_code == "processing_limit_exceeded"

    long_output = "B" * 60
    out_res = engine.inspect_output(long_output)
    assert out_res.passed is False
    assert out_res.reason_code == "processing_limit_exceeded"
