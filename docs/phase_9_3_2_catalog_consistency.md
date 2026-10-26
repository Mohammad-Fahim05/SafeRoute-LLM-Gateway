# Phase 9.3.2 — SafeRoute Active Model Catalog Consistency Audit Report

**Project**: SafeRoute LLM Gateway (`D:\SafeRoute LLM Gateway`)
**Auditor**: Senior AI Infrastructure Engineer & QA Auditor
**Audit Date**: October 25, 2026
**Status / Verdict**: **Pass** (All active, retired, restricted, and reference models audited, consistency enforced across allowlist, pricing catalog, capabilities registry, and provider routing)

---

## 1. Executive Summary

Phase 9.3.2 performed a comprehensive consistency audit across SafeRoute's active model allowlist (`app/config.py`), versioned pricing catalog (`app/pricing/config.json`), central model capability registry (`app/providers/capabilities.py`), provider adapters, and multi-provider failover validation (`app/providers/failover.py`).

The primary objectives were:
1. Audit and resolve inconsistencies across model definitions.
2. Investigate the catalog entry for `gpt-4o-mini` (OpenAI), verify adapter availability, and prevent unintended model selection while preserving historical pricing calculations.
3. Enforce lifecycle status constraints: retired models cannot be selected for new completions or failover; restricted legacy models follow an explicit configuration policy (`ALLOW_RESTRICTED_MODELS=false`); and all selectable models have verified provider adapters and matching capability entries.
4. Add comprehensive regression tests (`tests/unit/test_catalog_consistency.py`) and ensure 100% of existing tests pass without regressions.

---

## 2. Investigation of the OpenAI Entry (`gpt-4o-mini`)

### Audit Finding
- In Phase 8.4, `gpt-4o-mini` was included in `app/pricing/config.json` with `"status": "active"` and `"provider": "openai"` to serve as a cloud reference pricing benchmark.
- In Phase 9.3.1, `gpt-4o-mini` was registered in `MODEL_CAPABILITIES` with `status="active"` and capabilities set to `True`.
- **Architectural Reality**: SafeRoute **does not implement an OpenAI provider adapter**. The existing adapters are `MockProvider`, `OllamaProvider`, `ClaudeProvider`, and `GeminiProvider`. `gpt-4o-mini` was never in `allowed_models`, but having `"status": "active"` in the pricing catalog and capability registry was misleading and could lead to runtime routing errors or silent fallback to mock.

### Remediation Applied
1. **Pricing Catalog Updated**: In [app/pricing/config.json](file:///D:/SafeRoute%20LLM%20Gateway/app/pricing/config.json), updated `gpt-4o-mini`'s status to `"reference_unsupported"`. Explicitly documented in notes: *"Standard OpenAI cloud reference pricing per 1M tokens. Reference entry only; SafeRoute does not currently implement an OpenAI provider adapter."*
2. **Capability Registry Updated**: In [app/providers/capabilities.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/capabilities.py), set `status="reference_unsupported"`, `supports_text=False`, `supports_streaming=False`, `supports_tools=False`, and `supports_streaming_tools=False`.
3. **Provider Router Hardening**: In [app/providers/__init__.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/__init__.py), added an explicit check in `get_provider_for_model`: if a requested model has `provider == "openai"`, it raises `InvalidModelError("No provider adapter implemented for model '...' (provider: openai)")` rather than silently defaulting to `MockProvider`.
4. **Historical Pricing Preservation**: The input rate ($0.15/1M) and output rate ($0.60/1M) remain active in `config.json`, ensuring `PricingEngine.calculate_cost("gpt-4o-mini", ...)` remains 100% operational for historical audit logs and benchmark comparisons.

---

## 3. Lifecycle Policy Enforcement & Model Consistency Matrix

### Complete Catalog Audit Matrix

| Model ID | Provider | Lifecycle Status | Pricing Status | In Allowed Models? | Selectable for New Requests? | Failover Candidate? | Provider Adapter | Notes |
|---|---|---|---|---|---|---|---|---|
| `mock-model` | mock | active | active | Yes | Yes | Yes | `MockProvider` | Standard in-memory test double |
| `mock-timeout` | mock | active | active | Yes | Yes (throws) | Yes (throws) | `MockProvider` | Timeout simulation test double |
| `mock-error` | mock | active | active | Yes | Yes (throws) | Yes (throws) | `MockProvider` | 500 error simulation test double |
| `mock-malformed` | mock | active | active | Yes | Yes (throws) | Yes (throws) | `MockProvider` | Malformed payload simulation test double |
| `mock-rate-limit` | mock | active | active | Yes | Yes (throws) | Yes (throws) | `MockProvider` | 429 rate limit simulation test double |
| `mock-auth-error` | mock | active | active | Yes | Yes (throws) | Yes (throws) | `MockProvider` | 401 auth error simulation test double |
| `mock-server-error` | mock | active | active | Yes | Yes (throws) | Yes (throws) | `MockProvider` | 503 unavailable simulation test double |
| `mock-no-streaming` | mock | test | test | No (test only) | If allowed | If allowed (non-stream) | `MockProvider` | Non-streaming test double |
| `mock-no-tools` | mock | test | test | No (test only) | If allowed | If allowed (non-tool) | `MockProvider` | Non-tool test double |
| `llama3.2:1b` | ollama | active | active | Yes | Yes | Yes | `OllamaProvider` | Local inference ($0.0/1M) |
| `llama3.2` | ollama | active | active | Yes | Yes | Yes | `OllamaProvider` | Local inference ($0.0/1M) |
| `phi3` | ollama | active | active | Yes | Yes (text/stream) | Yes (non-tool) | `OllamaProvider` | Local inference; tools rejected |
| `mistral` | ollama | active | active | Yes | Yes | Yes | `OllamaProvider` | Local inference ($0.0/1M) |
| `claude-sonnet-4-6` | claude | active | active | Yes | Yes | Yes | `ClaudeProvider` | Active flagship Claude model |
| `claude-haiku-4-5-20251001` | claude | active | active | Yes | Yes | Yes | `ClaudeProvider` | Active high-speed Claude model |
| `gemini-3.8-flash` | gemini | active | active | Yes | Yes | Yes | `GeminiProvider` | Active intelligent Gemini model |
| `gemini-3.5-flash-lite` | gemini | active | Yes | Yes | Yes | Yes | `GeminiProvider` | Active high-throughput Gemini model |
| `claude-3-7-sonnet-20250219` | claude | retired | retired | No | No | No | `ClaudeProvider` | Retired Feb 19, 2026; historical pricing only |
| `claude-3-5-haiku-20241022` | claude | retired | retired | No | No | No | `ClaudeProvider` | Retired Feb 19, 2026; historical pricing only |
| `claude-3-5-sonnet-20241022` | claude | retired | retired | No | No | No | `ClaudeProvider` | Retired Oct 28, 2025; historical pricing only |
| `claude-3-haiku-20240307` | claude | retired | retired | No | No | No | `ClaudeProvider` | Retired Apr 20, 2026; historical pricing only |
| `gemini-2.5-flash` | gemini | restricted_legacy | restricted_legacy | No | If explicit flag | If explicit flag | `GeminiProvider` | Requires `ALLOW_RESTRICTED_MODELS=true` |
| `gemini-2.5-pro` | gemini | restricted_legacy | restricted_legacy | No | If explicit flag | If explicit flag | `GeminiProvider` | Requires `ALLOW_RESTRICTED_MODELS=true` |
| `gemini-1.5-flash` | gemini | retired | retired | No | No | No | `GeminiProvider` | Discontinued mid-2025; historical pricing only |
| `gemini-1.5-pro` | gemini | retired | retired | No | No | No | `GeminiProvider` | Discontinued mid-2025; historical pricing only |
| `gpt-4o-mini` | openai | reference_unsupported | reference_unsupported | No | No | No | None | Reference benchmark; no adapter implemented |

---

## 4. Policy Changes & Code Hardening

### 1. Restricted Legacy Models Policy (`ALLOW_RESTRICTED_MODELS`)
- Added `allow_restricted_models: bool = False` to `Settings` in [app/config.py](file:///D:/SafeRoute%20LLM%20Gateway/app/config.py) and documented it in [.env.example](file:///D:/SafeRoute%20LLM%20Gateway/.env.example).
- In [app/api/routes.py](file:///D:/SafeRoute%20LLM%20Gateway/app/api/routes.py#L254-L270), requests for restricted legacy models (`gemini-2.5-flash`, `gemini-2.5-pro`) are rejected with HTTP 400 (`invalid_model`) unless `ALLOW_RESTRICTED_MODELS=true` is explicitly set.
- In [app/providers/failover.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/failover.py#L215-L224), `validate_fallback_model` rejects restricted legacy models during failover unless `allow_restricted_models` is enabled.

### 2. Retired Models Rejection
- In [app/api/routes.py](file:///D:/SafeRoute%20LLM%20Gateway/app/api/routes.py#L226-L242), retired models are rejected for new requests in production environments with HTTP 400 (`invalid_model`: *"The model '...' is retired or deprecated and cannot be selected for new requests"*).
- In [app/providers/failover.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/failover.py#L209-L215), `validate_fallback_model` strictly rejects retired models as failover candidates across all environments.

### 3. Reference Unsupported Models Rejection
- In [app/api/routes.py](file:///D:/SafeRoute%20LLM%20Gateway/app/api/routes.py#L244-L252), requests for `reference_unsupported` models (such as `gpt-4o-mini`) are rejected with HTTP 400 (`invalid_model`: *"The model '...' is an external reference catalog entry and has no implemented provider adapter in SafeRoute"*).
- In [app/providers/__init__.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/__init__.py#L100-L105), `get_provider_for_model` rejects models requiring the unimplemented `openai` provider.

---

## 5. Files Changed

- [app/config.py](file:///D:/SafeRoute%20LLM%20Gateway/app/config.py): Added `allow_restricted_models: bool = False` configuration field.
- [.env.example](file:///D:/SafeRoute%20LLM%20Gateway/.env.example): Documented `ALLOW_RESTRICTED_MODELS` policy.
- [app/pricing/config.json](file:///D:/SafeRoute%20LLM%20Gateway/app/pricing/config.json): Updated `gpt-4o-mini` status to `reference_unsupported`; added explicit metadata entries for simulation mock models (`mock-timeout`, `mock-error`, etc.).
- [app/providers/capabilities.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/capabilities.py): Updated `gpt-4o-mini` status to `reference_unsupported` with capabilities set to `False`.
- [app/providers/__init__.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/__init__.py): Added explicit rejection for models with unimplemented provider adapters in `get_provider_for_model`.
- [app/providers/failover.py](file:///D:/SafeRoute%20LLM%20Gateway/app/providers/failover.py): Added failover candidate rejection for `reference_unsupported` models and restricted legacy models when policy is disabled.
- [app/api/routes.py](file:///D:/SafeRoute%20LLM%20Gateway/app/api/routes.py): Added early route-level verification for retired, reference unsupported, and restricted legacy models.
- [tests/unit/test_catalog_consistency.py](file:///D:/SafeRoute%20LLM%20Gateway/tests/unit/test_catalog_consistency.py): Added 7 regression tests verifying selectable model adapters, retired model rejection, restricted access policy, gpt-4o-mini reference rejection, pricing/capability agreement, and historical billing interpretability.
- [docs/phase_9_3_2_catalog_consistency.md](file:///D:/SafeRoute%20LLM%20Gateway/docs/phase_9_3_2_catalog_consistency.md): This report.

---

## 6. Actual Test Results

### 1. Catalog Consistency Regression Suite
```powershell
pytest tests/unit/test_catalog_consistency.py -v
```
```text
tests/unit/test_catalog_consistency.py::test_every_selectable_model_has_implemented_provider_adapter PASSED [ 14%]
tests/unit/test_catalog_consistency.py::test_retired_models_rejected_at_route_and_failover PASSED [ 28%]
tests/unit/test_catalog_consistency.py::test_restricted_legacy_models_follow_access_policy PASSED [ 42%]
tests/unit/test_catalog_consistency.py::test_reference_unsupported_openai_model_rejected PASSED [ 57%]
tests/unit/test_catalog_consistency.py::test_pricing_and_capabilities_agree_for_all_selectable_models PASSED [ 71%]
tests/unit/test_catalog_consistency.py::test_historical_billing_records_remain_interpretable PASSED [ 85%]
tests/unit/test_catalog_consistency.py::test_unknown_and_unverified_models_fail_safely PASSED [100%]

============================== 7 passed in 0.32s ==============================
```

### 2. Full Gateway Test Suite
```powershell
pytest -q
```
```text
320 passed, 1 warning in 38.54s
```

### 3. Quick Evaluation Suite
```powershell
python scripts/run_evaluation.py --mode quick
```
```text
============================================================================
Evaluation Summary:
  Total Cases           : 15
  Executed Cases        : 14
  Passed                : 14
  Failed                : 0
  Skipped               : 1 (optional live Ollama)
  Errored               : 0
  Pass Rate (Executed)  : 100.0%
  Completion Rate (All) : 93.33%
  Duration              : 847.0 ms
============================================================================
```

---

## 7. Remaining Limitations

1. **OpenAI Provider Support**: `gpt-4o-mini` is classified as `reference_unsupported` for historical billing and benchmarking reference only. An OpenAI provider adapter has not been implemented.
2. **Restricted Legacy Models**: `gemini-2.5-flash` and `gemini-2.5-pro` are restricted by Google to legacy accounts with prior activity. Enabling `ALLOW_RESTRICTED_MODELS=true` allows requests to pass through the gateway, but upstream Google API keys without grandfathered access will be rejected by Google AI.

---

## 8. Readiness for Review

Phase 9.3.2 is complete. All 320 tests pass. Execution stops here awaiting operator review.
