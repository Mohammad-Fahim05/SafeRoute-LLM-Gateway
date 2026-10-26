"""Model capability registry, verification provenance, and feature support checks.

Phase 9.3.1 Capability Audit:
Provides an explicit capability registry for all configured and historical models,
tracking text completion, streaming, tool/function calling, streaming tool deltas,
tool-choice modes, and JSON Schema limitations, with provenance classifications:
- 'verified_documentation': Verified against official provider documentation.
- 'verified_mocked_test': Verified only by mocked automated tests.
- 'inferred_family': Inferred from provider or model family characteristics.
- 'uncertain': Unverified or uncertain (fails safely).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ModelCapability:
    """Explicit capability record for an AI model."""

    model_id: str
    provider: str
    status: str  # "active", "retired", "restricted_legacy", "test"
    supports_text: bool = True
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_streaming_tools: bool = True
    supported_tool_choice_modes: List[str] = field(default_factory=list)
    json_schema_limitations: Optional[str] = None
    evidence_level: str = "verified_documentation"  # verified_documentation, verified_mocked_test, inferred_family, uncertain
    evidence_source: Optional[str] = None
    notes: Optional[str] = None


# Explicit capability records for all known models in SafeRoute
MODEL_CAPABILITIES: Dict[str, ModelCapability] = {
    # --------------------------------------------------------------------------
    # Mock Provider Models (Testing doubles)
    # --------------------------------------------------------------------------
    "mock-model": ModelCapability(
        model_id="mock-model",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Standard mock model supporting deterministic text, streaming, and tool calls.",
    ),
    "mock-timeout": ModelCapability(
        model_id="mock-timeout",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Simulates upstream provider timeout.",
    ),
    "mock-error": ModelCapability(
        model_id="mock-error",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Simulates upstream provider 500 error.",
    ),
    "mock-malformed": ModelCapability(
        model_id="mock-malformed",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Simulates malformed response payload; tool calling is explicitly disabled.",
    ),
    "mock-rate-limit": ModelCapability(
        model_id="mock-rate-limit",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Simulates upstream 429 rate limit exceeded.",
    ),
    "mock-auth-error": ModelCapability(
        model_id="mock-auth-error",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Simulates upstream 401 unauthorized.",
    ),
    "mock-server-error": ModelCapability(
        model_id="mock-server-error",
        provider="mock",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Simulates upstream 503 service unavailable.",
    ),
    "mock-no-streaming": ModelCapability(
        model_id="mock-no-streaming",
        provider="mock",
        status="test",
        supports_text=True,
        supports_streaming=False,
        supports_tools=True,
        supports_streaming_tools=False,
        supported_tool_choice_modes=["auto", "none", "required", "function"],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Dedicated non-streaming test model for streaming capability validation.",
    ),
    "mock-no-tools": ModelCapability(
        model_id="mock-no-tools",
        provider="mock",
        status="test",
        supports_text=True,
        supports_streaming=True,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations=None,
        evidence_level="verified_mocked_test",
        evidence_source="In-memory MockProvider test harness",
        notes="Dedicated non-tool test model for tool capability validation.",
    ),
    # --------------------------------------------------------------------------
    # Ollama Local Models
    # --------------------------------------------------------------------------
    "llama3.2:1b": ModelCapability(
        model_id="llama3.2:1b",
        provider="ollama",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto"],
        json_schema_limitations="High hallucination and over-triggering risk due to 1B parameter size.",
        evidence_level="verified_documentation",
        evidence_source="https://ollama.com/library/llama3.2:1b",
        notes="Ollama supports tool calling on 1B, but small parameter size limits complex schema adherence.",
    ),
    "qwen2.5-coder:7b-instruct-q4_K_M": ModelCapability(
        model_id="qwen2.5-coder:7b-instruct-q4_K_M",
        provider="ollama",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto"],
        json_schema_limitations="Quantized GGUF local model.",
        evidence_level="verified_documentation",
        evidence_source="https://ollama.com/library/qwen2.5-coder",
        notes="Qwen 2.5 Coder 7B 4-bit quantized instruct model running locally via Ollama.",
    ),
    "llama3.2": ModelCapability(
        model_id="llama3.2",
        provider="ollama",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto"],
        json_schema_limitations="Requires structured JSON response parsing by Ollama template.",
        evidence_level="verified_documentation",
        evidence_source="https://ollama.com/library/llama3.2",
        notes="Llama 3.2 3B in Ollama natively supports tool calling and streaming.",
    ),
    "llama3.1:8b": ModelCapability(
        model_id="llama3.1:8b",
        provider="ollama",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto"],
        json_schema_limitations="Requires structured JSON response parsing by Ollama template.",
        evidence_level="verified_documentation",
        evidence_source="https://ollama.com/library/llama3.1",
        notes="Llama 3.1 8B in Ollama supports function/tool calling and streaming.",
    ),
    "phi3": ModelCapability(
        model_id="phi3",
        provider="ollama",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="No native tool/function calling fine-tuning or template in Ollama.",
        evidence_level="verified_documentation",
        evidence_source="https://ollama.com/library/phi3",
        notes="Microsoft Phi-3 Mini supports text and streaming completions, but lacks native tool support.",
    ),
    "mistral": ModelCapability(
        model_id="mistral",
        provider="ollama",
        status="active",
        supports_text=True,
        supports_streaming=True,
        supports_tools=True,
        supports_streaming_tools=True,
        supported_tool_choice_modes=["auto"],
        json_schema_limitations="Mistral v0.3 tool calling template supported in Ollama.",
        evidence_level="verified_documentation",
        evidence_source="https://ollama.com/library/mistral",
        notes="Mistral 7B (Instruct v0.3) supports tool calling and streaming in Ollama.",
    ),
    # --------------------------------------------------------------------------
    # Historical Reference Models (No active provider adapters)
    # --------------------------------------------------------------------------
    "claude-sonnet-4-6": ModelCapability(
        model_id="claude-sonnet-4-6",
        provider="claude",
        status="reference_unsupported",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Anthropic adapter removed from gateway.",
        evidence_level="verified_documentation",
        evidence_source="https://platform.claude.com/docs/en/about-claude/pricing",
        notes="Historical reference model; no provider adapter implemented.",
    ),
    "claude-haiku-4-5-20251001": ModelCapability(
        model_id="claude-haiku-4-5-20251001",
        provider="claude",
        status="reference_unsupported",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Anthropic adapter removed from gateway.",
        evidence_level="verified_documentation",
        evidence_source="https://platform.claude.com/docs/en/about-claude/pricing",
        notes="Historical reference model; no provider adapter implemented.",
    ),
    "claude-3-7-sonnet-20250219": ModelCapability(
        model_id="claude-3-7-sonnet-20250219",
        provider="claude",
        status="retired",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Draft-07 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://platform.claude.com/docs/en/about-claude/model-deprecations",
        notes="Retired Feb 19, 2026 on native API; retained in historical pricing catalog.",
    ),
    "claude-3-5-haiku-20241022": ModelCapability(
        model_id="claude-3-5-haiku-20241022",
        provider="claude",
        status="retired",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Draft-07 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://platform.claude.com/docs/en/about-claude/model-deprecations",
        notes="Retired Feb 19, 2026 on native API; retained in historical pricing catalog.",
    ),
    "claude-3-5-sonnet-20241022": ModelCapability(
        model_id="claude-3-5-sonnet-20241022",
        provider="claude",
        status="retired",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Draft-07 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://platform.claude.com/docs/en/about-claude/model-deprecations",
        notes="Retired Oct 28, 2025 on native API; retained in historical pricing catalog.",
    ),
    "claude-3-haiku-20240307": ModelCapability(
        model_id="claude-3-haiku-20240307",
        provider="claude",
        status="retired",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Draft-07 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://platform.claude.com/docs/en/about-claude/model-deprecations",
        notes="Retired Apr 20, 2026 on native API; retained in historical pricing catalog.",
    ),
    "gemini-3.8-flash": ModelCapability(
        model_id="gemini-3.8-flash",
        provider="gemini",
        status="reference_unsupported",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Gemini adapter removed from gateway.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/pricing",
        notes="Historical reference model; no provider adapter implemented.",
    ),
    "gemini-3.5-flash-lite": ModelCapability(
        model_id="gemini-3.5-flash-lite",
        provider="gemini",
        status="reference_unsupported",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="Gemini adapter removed from gateway.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/pricing",
        notes="Historical reference model; no provider adapter implemented.",
    ),
    "gemini-2.5-flash": ModelCapability(
        model_id="gemini-2.5-flash",
        provider="gemini",
        status="restricted_legacy",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="OpenAPI 3.0 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/gemini-api/docs/deprecations",
        notes="Restricted to prior accounts; not in default allowlist.",
    ),
    "gemini-2.5-pro": ModelCapability(
        model_id="gemini-2.5-pro",
        provider="gemini",
        status="restricted_legacy",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="OpenAPI 3.0 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/gemini-api/docs/deprecations",
        notes="Restricted to prior accounts; not in default allowlist.",
    ),
    "gemini-2.0-flash": ModelCapability(
        model_id="gemini-2.0-flash",
        provider="gemini",
        status="reference_unsupported",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="OpenAPI 3.0 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/gemini-api/docs/models",
        notes="Historical reference model; no provider adapter implemented.",
    ),
    "gemini-1.5-flash": ModelCapability(
        model_id="gemini-1.5-flash",
        provider="gemini",
        status="retired",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="OpenAPI 3.0 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/pricing",
        notes="Discontinued mid-2025; retained in historical pricing catalog.",
    ),
    "gemini-1.5-pro": ModelCapability(
        model_id="gemini-1.5-pro",
        provider="gemini",
        status="retired",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="OpenAPI 3.0 subset.",
        evidence_level="verified_documentation",
        evidence_source="https://ai.google.dev/pricing",
        notes="Discontinued mid-2025; retained in historical pricing catalog.",
    ),
    # --------------------------------------------------------------------------
    # OpenAI Catalog Reference (not routed by gateway)
    # --------------------------------------------------------------------------
    "gpt-4o-mini": ModelCapability(
        model_id="gpt-4o-mini",
        provider="openai",
        status="reference_unsupported",
        supports_text=False,
        supports_streaming=False,
        supports_tools=False,
        supports_streaming_tools=False,
        supported_tool_choice_modes=[],
        json_schema_limitations="OpenAI provider adapter is not implemented in SafeRoute.",
        evidence_level="verified_documentation",
        evidence_source="https://openai.com/api/pricing",
        notes="Reference model in pricing catalog. Not selectable; SafeRoute does not implement an OpenAI provider adapter.",
    ),
}


def get_model_capabilities(model: str) -> Optional[ModelCapability]:
    """Retrieve the explicit capability record for a model, if registered."""
    if not model:
        return None
    cleaned = model.strip()
    # Direct lookup
    if cleaned in MODEL_CAPABILITIES:
        return MODEL_CAPABILITIES[cleaned]
    # Case-insensitive lookup
    cleaned_lower = cleaned.lower()
    for mid, cap in MODEL_CAPABILITIES.items():
        if mid.lower() == cleaned_lower:
            return cap
    return None


def model_supports_tools(model: str) -> bool:
    """Return whether the specified model identifier supports tool/function calling.

    Resolution precedence:
    1. Direct registry lookup if model is explicitly registered.
    2. Explicit non-tool keyword checks ('no-tools', 'phi3', 'mock-malformed').
    3. Safe family heuristics for unknown variants with clear logging.
    """
    if not model:
        return False
    clean_model = model.strip().lower()

    # 1. Explicit negatives
    if "no-tools" in clean_model:
        return False
    if "phi3" in clean_model or clean_model == "mock-malformed":
        return False

    # 2. Registered capabilities lookup
    cap = get_model_capabilities(model)
    if cap is not None:
        return cap.supports_tools

    # 3. Family-based heuristics for unregistered model variants
    if (
        clean_model.startswith("llama3")
        or clean_model.startswith("mistral")
        or clean_model.startswith("mock-")
        or clean_model == "mock-model"
    ):
        return True

    return False


def model_supports_streaming(model: str) -> bool:
    """Return whether the specified model identifier supports streaming completions.

    Resolution precedence:
    1. Direct registry lookup if model is explicitly registered.
    2. Explicit non-streaming keyword checks ('no-streaming').
    3. Safe family heuristics for unknown variants.
    """
    if not model:
        return False
    clean_model = model.strip().lower()

    # 1. Explicit negatives
    if "no-streaming" in clean_model:
        return False

    # 2. Registered capabilities lookup
    cap = get_model_capabilities(model)
    if cap is not None:
        return cap.supports_streaming

    # 3. Family-based heuristics for unregistered model variants
    if (
        clean_model.startswith("llama3")
        or clean_model.startswith("mistral")
        or clean_model.startswith("phi3")
        or clean_model.startswith("mock-")
        or clean_model == "mock-model"
    ):
        return True

    return False


def model_supports_streaming_tools(model: str) -> bool:
    """Return whether the specified model supports tool calling during streaming."""
    if not model_supports_tools(model):
        return False
    if not model_supports_streaming(model):
        return False

    cap = get_model_capabilities(model)
    if cap is not None:
        return cap.supports_streaming_tools

    return True
