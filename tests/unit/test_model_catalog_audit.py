"""Focused unit and regression tests for Phase 8.4 Model Catalog Audit & Verification."""

from decimal import Decimal
import json
from pathlib import Path
import re
import pytest

from app.config import Settings
from app.pricing.calculator import PricingEngine, _PRICING_FILE
from app.providers import get_provider_for_model
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider


def test_catalog_file_integrity_and_schema():
    """Verify config.json exists, parses cleanly, and adheres to the catalog schema."""
    assert _PRICING_FILE.exists()
    with open(_PRICING_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "pricing_version" in data
    assert data["pricing_version"] == "2026-10-v3"
    assert data.get("currency") == "USD"
    assert "models" in data
    assert len(data["models"]) >= 10


def test_all_default_allowed_models_have_valid_catalog_entries():
    """Verify every model in Settings().allowed_models exists in the pricing catalog with active status."""
    settings = Settings()
    engine = PricingEngine()

    for model_id in settings.allowed_models:
        if model_id.startswith("mock-") and model_id != "mock-model":
            # Simulation variants (mock-timeout, mock-error, mock-malformed)
            continue

        assert model_id in engine.models, f"Default allowed model '{model_id}' is missing from config.json"
        entry = engine.models[model_id]
        assert entry.get("status") == "active", f"Default model '{model_id}' must have status 'active', got {entry.get('status')}"


def test_retired_and_restricted_models_excluded_from_default_allowlist():
    """Verify retired and restricted legacy models are never present in the default allowed_models list."""
    settings = Settings()
    engine = PricingEngine()

    retired_or_restricted_ids = [
        "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    for model_id in retired_or_restricted_ids:
        assert model_id not in settings.allowed_models, f"Retired/restricted model '{model_id}' must not be in default allowed_models"
        assert model_id in engine.models, f"Historical model '{model_id}' must be preserved in config.json"
        status = engine.models[model_id].get("status")
        assert status in ("retired", "restricted_legacy"), f"Expected retired or restricted_legacy for '{model_id}', got '{status}'"


def test_pricing_metadata_types_units_and_verification_dates():
    """Verify all cloud pricing entries contain valid Decimal rates, source URLs, and ISO verification dates."""
    engine = PricingEngine()
    date_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for model_id, meta in engine.models.items():
        if meta.get("is_mock"):
            continue

        assert "input_cost_per_1m" in meta, f"Missing input_cost_per_1m for {model_id}"
        assert "output_cost_per_1m" in meta, f"Missing output_cost_per_1m for {model_id}"

        # Decimal parseability
        in_rate = Decimal(str(meta["input_cost_per_1m"]))
        out_rate = Decimal(str(meta["output_cost_per_1m"]))
        assert in_rate >= Decimal("0.0"), f"Negative input rate for {model_id}"
        assert out_rate >= Decimal("0.0"), f"Negative output rate for {model_id}"

        # Cloud models must have source_url and verification_date
        if not meta.get("is_local", False):
            assert "source_url" in meta, f"Missing source_url for cloud model {model_id}"
            assert meta["source_url"].startswith("https://"), f"source_url must be HTTPS for {model_id}"
            assert "verification_date" in meta, f"Missing verification_date for cloud model {model_id}"
            assert date_regex.match(meta["verification_date"]), f"Invalid verification_date format for {model_id}"


def test_unknown_token_counts_produce_none_costs_not_zero():
    """Verify unknown or missing token counts never fabricate zero costs."""
    engine = PricingEngine()

    # Cloud model with None tokens
    res = engine.calculate_cost("claude-sonnet-4-6", None, None, provider="claude")
    assert res.calculation_status == "missing_usage"
    assert res.input_cost is None
    assert res.output_cost is None
    assert res.total_cost is None

    # Local model with None tokens
    res_local = engine.calculate_cost("llama3.2:1b", None, None, provider="ollama")
    assert res_local.calculation_status == "missing_usage"
    assert res_local.total_cost is None


def test_historical_pricing_records_remain_accurately_computable():
    """Verify historical models compute exact Decimal costs matching their historical rates without silent alteration."""
    engine = PricingEngine()

    # claude-3-7-sonnet-20250219: 3.00 in / 15.00 out per 1M
    res_c37 = engine.calculate_cost("claude-3-7-sonnet-20250219", 10_000, 2_000, provider="claude")
    assert res_c37.calculation_status == "calculated"
    assert res_c37.total_cost == Decimal("0.060000")

    # gemini-2.5-flash: 0.30 in / 2.50 out per 1M
    res_g25 = engine.calculate_cost("gemini-2.5-flash", 20_000, 10_000, provider="gemini")
    assert res_g25.calculation_status == "calculated"
    assert res_g25.total_cost == Decimal("0.031000")

    # gemini-1.5-flash: 0.075 in / 0.30 out per 1M
    res_g15 = engine.calculate_cost("gemini-1.5-flash", 20_000, 10_000, provider="gemini")
    assert res_g15.calculation_status == "calculated"
    assert res_g15.total_cost == Decimal("0.004500")


def test_default_models_routing_integrity():
    """Verify all default allowed models route to their intended provider adapter."""
    settings = Settings()

    # Local Ollama models
    settings_ollama = Settings(active_provider="ollama")
    for m in ("llama3.2:1b", "llama3.2", "phi3", "mistral"):
        prov = get_provider_for_model(m, settings_ollama)
        assert isinstance(prov, OllamaProvider)
        assert prov.name == "ollama"

    # Mock model
    prov_mock = get_provider_for_model("mock-model", settings)
    assert isinstance(prov_mock, MockProvider)
    assert prov_mock.name == "mock"
