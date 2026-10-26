"""Unit tests for pricing engine and Decimal cost calculation."""

from decimal import Decimal
from app.pricing.calculator import PricingEngine, PricingResult


def test_pricing_arithmetic_exact_decimal():
    """Requirement 11: Verify pricing formula: (in * in_rate + out * out_rate) / 1,000,000."""
    engine = PricingEngine()
    # gpt-4o-mini rates in config.json: in=0.15, out=0.60 per 1M tokens
    result = engine.calculate_cost(
        model="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=500,
        provider="openai",
    )
    assert result.calculation_status == "calculated"
    assert result.pricing_version == "2026-10-v3"
    assert result.currency == "USD"

    # expected: (1000 * 0.15 + 500 * 0.60) / 1,000,000 = (150 + 300) / 1,000,000 = 0.000450
    assert result.input_cost == Decimal("0.000150")
    assert result.output_cost == Decimal("0.000300")
    assert result.total_cost == Decimal("0.000450")


def test_pricing_local_ollama_free_tier():
    """Requirement 14: Local Ollama inference has zero external API charge."""
    engine = PricingEngine()
    result = engine.calculate_cost(
        model="llama3.2:1b",
        input_tokens=2500,
        output_tokens=1200,
        provider="ollama",
    )
    assert result.calculation_status == "free_tier_local"
    assert result.input_cost == Decimal("0.000000")
    assert result.output_cost == Decimal("0.000000")
    assert result.total_cost == Decimal("0.000000")


def test_pricing_mock_excluded():
    """Requirement 13: Mock provider estimates are excluded from cloud spending."""
    engine = PricingEngine()
    result = engine.calculate_cost(
        model="mock-model",
        input_tokens=100,
        output_tokens=50,
        provider="mock",
    )
    assert result.calculation_status == "mock_excluded"
    assert result.total_cost is None


def test_pricing_unknown_model():
    """Requirement 12: Unknown models without pricing data are labeled unknown_model."""
    engine = PricingEngine()
    result = engine.calculate_cost(
        model="unconfigured-custom-llm-v1",
        input_tokens=1000,
        output_tokens=500,
        provider="custom",
    )
    assert result.calculation_status == "unknown_model"
    assert result.total_cost is None


def test_pricing_missing_usage():
    """Requirement 10: Missing token counts produce missing_usage calculation status and null cost."""
    engine = PricingEngine()
    # Cloud model with missing tokens
    result = engine.calculate_cost(
        model="gpt-4o-mini",
        input_tokens=None,
        output_tokens=None,
        provider="openai",
    )
    assert result.calculation_status == "missing_usage"
    assert result.total_cost is None

    # Local model with missing tokens also preserves unknown cost
    result_local = engine.calculate_cost(
        model="llama3.2:1b",
        input_tokens=None,
        output_tokens=50,
        provider="ollama",
    )
    assert result_local.calculation_status == "missing_usage"
    assert result_local.total_cost is None


def test_pricing_explicit_zero_tokens():
    """Requirement 10: Explicit zero token counts compute genuine zero cost and are not confused with missing counts."""
    engine = PricingEngine()
    result = engine.calculate_cost(
        model="gpt-4o-mini",
        input_tokens=0,
        output_tokens=0,
        provider="openai",
    )
    assert result.calculation_status == "calculated"
    assert result.input_cost == Decimal("0.000000")
    assert result.output_cost == Decimal("0.000000")
    assert result.total_cost == Decimal("0.000000")


def test_pricing_claude_models():
    """Verify Decimal pricing for active and historical Claude models."""
    engine = PricingEngine()

    # Active: claude-sonnet-4-6 (in=3.00, out=15.00 per 1M)
    res_sonnet_46 = engine.calculate_cost(
        model="claude-sonnet-4-6",
        input_tokens=10_000,  # 10k * 3.00 / 1M = 0.030000
        output_tokens=2_000,  # 2k * 15.00 / 1M = 0.030000
        provider="claude",
    )
    assert res_sonnet_46.calculation_status == "calculated"
    assert res_sonnet_46.input_cost == Decimal("0.030000")
    assert res_sonnet_46.output_cost == Decimal("0.030000")
    assert res_sonnet_46.total_cost == Decimal("0.060000")

    # Active: claude-haiku-4-5-20251001 (in=1.00, out=5.00 per 1M)
    res_haiku_45 = engine.calculate_cost(
        model="claude-haiku-4-5-20251001",
        input_tokens=10_000,  # 10k * 1.00 / 1M = 0.010000
        output_tokens=2_000,  # 2k * 5.00 / 1M = 0.010000
        provider="claude",
    )
    assert res_haiku_45.calculation_status == "calculated"
    assert res_haiku_45.input_cost == Decimal("0.010000")
    assert res_haiku_45.output_cost == Decimal("0.010000")
    assert res_haiku_45.total_cost == Decimal("0.020000")

    # Historical: claude-3-7-sonnet-20250219 (in=3.00, out=15.00 per 1M)
    res_sonnet_37 = engine.calculate_cost(
        model="claude-3-7-sonnet-20250219",
        input_tokens=10_000,
        output_tokens=2_000,
        provider="claude",
    )
    assert res_sonnet_37.calculation_status == "calculated"
    assert res_sonnet_37.total_cost == Decimal("0.060000")

    # Historical: claude-3-5-haiku-20241022 (in=0.80, out=4.00 per 1M)
    res_haiku_35 = engine.calculate_cost(
        model="claude-3-5-haiku-20241022",
        input_tokens=10_000,
        output_tokens=2_000,
        provider="claude",
    )
    assert res_haiku_35.calculation_status == "calculated"
    assert res_haiku_35.total_cost == Decimal("0.016000")

    # Historical: claude-3-5-sonnet-20241022 (in=3.00, out=15.00 per 1M)
    res_sonnet_legacy = engine.calculate_cost(
        model="claude-3-5-sonnet-20241022",
        input_tokens=10_000,
        output_tokens=2_000,
        provider="claude",
    )
    assert res_sonnet_legacy.calculation_status == "calculated"
    assert res_sonnet_legacy.total_cost == Decimal("0.060000")

    # Historical: claude-3-haiku-20240307 (in=0.25, out=1.25 per 1M)
    res_haiku_legacy = engine.calculate_cost(
        model="claude-3-haiku-20240307",
        input_tokens=10_000,
        output_tokens=4_000,
        provider="claude",
    )
    assert res_haiku_legacy.calculation_status == "calculated"
    assert res_haiku_legacy.total_cost == Decimal("0.007500")


def test_pricing_gemini_models():
    """Verify Decimal pricing for active, restricted legacy, and retired Gemini models."""
    engine = PricingEngine()

    # Active: gemini-3.8-flash (in=0.75, out=3.75 per 1M)
    res_flash_38 = engine.calculate_cost(
        model="gemini-3.8-flash",
        input_tokens=20_000,  # 20k * 0.75 / 1M = 0.015000
        output_tokens=10_000,  # 10k * 3.75 / 1M = 0.037500
        provider="gemini",
    )
    assert res_flash_38.calculation_status == "calculated"
    assert res_flash_38.input_cost == Decimal("0.015000")
    assert res_flash_38.output_cost == Decimal("0.037500")
    assert res_flash_38.total_cost == Decimal("0.052500")

    # Active: gemini-3.5-flash-lite (in=0.30, out=2.50 per 1M)
    res_flash_lite_35 = engine.calculate_cost(
        model="gemini-3.5-flash-lite",
        input_tokens=20_000,  # 20k * 0.30 / 1M = 0.006000
        output_tokens=10_000,  # 10k * 2.50 / 1M = 0.025000
        provider="gemini",
    )
    assert res_flash_lite_35.calculation_status == "calculated"
    assert res_flash_lite_35.input_cost == Decimal("0.006000")
    assert res_flash_lite_35.output_cost == Decimal("0.025000")
    assert res_flash_lite_35.total_cost == Decimal("0.031000")

    # Restricted legacy: gemini-2.5-flash (in=0.30, out=2.50 per 1M)
    res_flash_25 = engine.calculate_cost(
        model="gemini-2.5-flash",
        input_tokens=20_000,
        output_tokens=10_000,
        provider="gemini",
    )
    assert res_flash_25.calculation_status == "calculated"
    assert res_flash_25.total_cost == Decimal("0.031000")

    # Restricted legacy: gemini-2.5-pro (in=1.25, out=10.00 per 1M)
    res_pro_25 = engine.calculate_cost(
        model="gemini-2.5-pro",
        input_tokens=10_000,
        output_tokens=2_000,
        provider="gemini",
    )
    assert res_pro_25.calculation_status == "calculated"
    assert res_pro_25.total_cost == Decimal("0.032500")

    # Retired: gemini-1.5-flash (in=0.075, out=0.30 per 1M)
    res_flash_legacy = engine.calculate_cost(
        model="gemini-1.5-flash",
        input_tokens=20_000,
        output_tokens=10_000,
        provider="gemini",
    )
    assert res_flash_legacy.calculation_status == "calculated"
    assert res_flash_legacy.total_cost == Decimal("0.004500")

    # Retired: gemini-1.5-pro (in=1.25, out=5.00 per 1M)
    res_pro_legacy = engine.calculate_cost(
        model="gemini-1.5-pro",
        input_tokens=10_000,
        output_tokens=2_000,
        provider="gemini",
    )
    assert res_pro_legacy.calculation_status == "calculated"
    assert res_pro_legacy.total_cost == Decimal("0.022500")
