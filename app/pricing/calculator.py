"""Versioned model pricing loader and exact Decimal cost calculation."""

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Optional

_PRICING_FILE = Path(__file__).parent / "config.json"
_ONE_MILLION = Decimal("1000000")


@dataclass(frozen=True)
class PricingResult:
    """Calculated cost outcome and audit metadata."""

    pricing_version: str
    input_cost: Optional[Decimal]
    output_cost: Optional[Decimal]
    total_cost: Optional[Decimal]
    currency: str
    calculation_status: str  # calculated, free_tier_local, mock_excluded, missing_usage, unknown_model


class PricingEngine:
    """Calculates model costs using versioned rates and Decimal arithmetic."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or _PRICING_FILE
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            self.version = "unknown"
            self.currency = "USD"
            self.models: Dict[str, Any] = {}
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.version = data.get("pricing_version", "2026-10-v1")
        self.currency = data.get("currency", "USD")
        self.models = data.get("models", {})

    def calculate_cost(
        self,
        model: str,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        provider: str,
    ) -> PricingResult:
        """Calculate estimated cost using Decimal arithmetic.

        Rules:
        - If provider is mock or model is mock: mock_excluded.
        - If model not in pricing table: unknown_model.
        - If model is local (e.g. Ollama): free_tier_local (0.000000 USD).
        - If input_tokens or output_tokens is None: missing_usage.
        - Otherwise: calculated.
        """
        # 1. Mock exclusion rule
        if provider == "mock" or model.startswith("mock-") or self.models.get(model, {}).get("is_mock"):
            return PricingResult(
                pricing_version=self.version,
                input_cost=None,
                output_cost=None,
                total_cost=None,
                currency=self.currency,
                calculation_status="mock_excluded",
            )

        # 2. Unknown model rule
        model_info = self.models.get(model)
        if not model_info:
            return PricingResult(
                pricing_version=self.version,
                input_cost=None,
                output_cost=None,
                total_cost=None,
                currency=self.currency,
                calculation_status="unknown_model",
            )

        # 3. Missing token usage rule (costs remain unknown if token counts unavailable)
        if input_tokens is None or output_tokens is None:
            return PricingResult(
                pricing_version=self.version,
                input_cost=None,
                output_cost=None,
                total_cost=None,
                currency=self.currency,
                calculation_status="missing_usage",
            )

        # 4. Local model rule (Ollama inference has no external API charge when tokens known)
        if model_info.get("is_local", False):
            zero = Decimal("0.000000")
            return PricingResult(
                pricing_version=self.version,
                input_cost=zero,
                output_cost=zero,
                total_cost=zero,
                currency=self.currency,
                calculation_status="free_tier_local",
            )


        # 5. Cloud per-token calculation
        input_rate = Decimal(str(model_info.get("input_cost_per_1m", "0.0")))
        output_rate = Decimal(str(model_info.get("output_cost_per_1m", "0.0")))

        in_cost = (Decimal(input_tokens) * input_rate / _ONE_MILLION).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        out_cost = (Decimal(output_tokens) * output_rate / _ONE_MILLION).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        total_cost = in_cost + out_cost

        return PricingResult(
            pricing_version=self.version,
            input_cost=in_cost,
            output_cost=out_cost,
            total_cost=total_cost,
            currency=self.currency,
            calculation_status="calculated",
        )


pricing_engine = PricingEngine()
