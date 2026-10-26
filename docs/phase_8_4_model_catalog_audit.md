# Phase 8.4 Model Catalog Audit & Verification Report

**Project**: SafeRoute LLM Gateway (`D:\SafeRoute LLM Gateway`)
**Auditor**: Senior AI Infrastructure Engineer & QA Auditor
**Audit Date**: October 25, 2026
**Status / Verdict**: **Pass** (All active and historical models verified against official documentation)

---

## 1. Executive Summary

Phase 8.4 performed a comprehensive, evidence-based audit of SafeRoute's provider model catalog, allowed-model configuration, and versioned pricing database before beginning Phase 9 (Dynamic Multi-Provider Failover & Streaming).

The audit cross-referenced configured models against live official documentation from Anthropic ([platform.claude.com](https://platform.claude.com/docs/en/about-claude/model-deprecations)) and Google AI ([ai.google.dev](https://ai.google.dev/pricing)).

Key Audit Conclusions:
1. **Active Claude Lineup**: `claude-sonnet-4-6` ($3.00 / $15.00 per 1M) and `claude-haiku-4-5-20251001` ($1.00 / $5.00 per 1M) are fully verified as currently supported active models on Anthropic's developer Messages API.
2. **Active Gemini Lineup**: `gemini-3.8-flash` ($0.75 / $3.75 per 1M introductory through Dec 31, 2026) and `gemini-3.5-flash-lite` ($0.30 / $2.50 per 1M) are fully verified active GA models on the Gemini Developer API (`generateContent`).
3. **Disallowed / Retired Models**: Retired entries (`claude-3-7-sonnet-20250219`, `claude-3-5-haiku-20241022`, `claude-3-5-sonnet-20241022`, `claude-3-haiku-20240307`, `gemini-1.5-flash`, `gemini-1.5-pro`) and restricted access entries (`gemini-2.5-flash`, `gemini-2.5-pro`) are verified excluded from default `allowed_models` in `app/config.py`.
4. **Historical Billing Preservation**: In `app/pricing/config.json` (version `2026-10-v3`), historical models remain present with exact historical Decimal rates and deprecation metadata to ensure past SQLite request records and audit exports are never recalculated or invalidated.
5. **Issue Identified & Fixed**: The default `allowed_models` list included the local model `mistral`, but `mistral` was omitted from `app/pricing/config.json`. It was added as a free-tier local Ollama model (`input_cost_per_1m: "0.0"`, `output_cost_per_1m: "0.0"`), ensuring 100% agreement between allowlists and catalog entries.
6. **Testing & QA**: Added dedicated audit regression suite `tests/unit/test_model_catalog_audit.py` (7 tests). Full pytest suite passed (**223 passed in 10.87s**). Quick evaluation passed (**14 passed, 1 skipped, 0 failed** in 853.98ms).

---

## 2. Comparison Table: Model Catalog Audit

| Provider | Configured Model ID | Verified Status | Input Price (USD / 1M) | Output Price (USD / 1M) | Pricing Conditions | Official Source | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Anthropic** | `claude-sonnet-4-6` | **Active** (GA) | **$3.00** | **$15.00** | Flat rate across 1M context. 5m cache write: $3.75/M; 1h cache write: $6.00/M; cache read: $0.30/M. Batch: 50% discount. US-only geo: +10%. | [Claude Pricing](https://platform.claude.com/docs/en/about-claude/pricing) & [Model Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | **Keep as default active Claude flagship** |
| **Anthropic** | `claude-haiku-4-5-20251001` | **Active** (GA) | **$1.00** | **$5.00** | Base rate. 5m cache write: $1.25/M; 1h cache write: $2.00/M; cache read: $0.10/M. Batch: 50% discount. | [Claude Pricing](https://platform.claude.com/docs/en/about-claude/pricing) & [Model Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | **Keep as default active Claude high-speed model** |
| **Anthropic** | `claude-3-7-sonnet-20250219` | **Retired** | $3.00 (Hist) | $15.00 (Hist) | Deprecated Oct 28, 2025; retired Feb 19, 2026 on native API. Superseded by `claude-sonnet-4-6`. | [Claude Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | **Retain in pricing catalog only (status: retired); exclude from defaults** |
| **Anthropic** | `claude-3-5-haiku-20241022` | **Retired** | $0.80 (Hist) | $4.00 (Hist) | Deprecated Dec 19, 2025; retired Feb 19, 2026 on native API. Superseded by `claude-haiku-4-5-20251001`. | [Claude Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | **Retain in pricing catalog only (status: retired); exclude from defaults** |
| **Anthropic** | `claude-3-5-sonnet-20241022` | **Retired** | $3.00 (Hist) | $15.00 (Hist) | Deprecated Aug 13, 2025; retired Oct 28, 2025 on native API. | [Claude Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | **Retain in pricing catalog only (status: retired); exclude from defaults** |
| **Anthropic** | `claude-3-haiku-20240307` | **Retired** | $0.25 (Hist) | $1.25 (Hist) | Deprecated Feb 19, 2026; retired Apr 20, 2026 on native API. | [Claude Deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | **Retain in pricing catalog only (status: retired); exclude from defaults** |
| **Google** | `gemini-3.8-flash` | **Active** (GA) | **$0.75** | **$3.75** | Introductory pricing through Dec 31, 2026; standard rate $1.50 in / $7.50 out starting Jan 1, 2027. Output tokens include thinking tokens. Context up to 1,048,576 tokens. | [Google AI Pricing](https://ai.google.dev/pricing) & [Gemini Models](https://ai.google.dev/gemini-api/docs/models) | **Keep as default active Gemini flagship** |
| **Google** | `gemini-3.5-flash-lite` | **Active** (GA) | **$0.30** | **$2.50** | Optimized for high-throughput execution. Context window up to 1,048,576 tokens. | [Google AI Pricing](https://ai.google.dev/pricing) & [Gemini Models](https://ai.google.dev/gemini-api/docs/models) | **Keep as default active Gemini high-throughput model** |
| **Google** | `gemini-2.5-flash` | **Restricted Legacy** | $0.30 (Legacy) | $2.50 (Legacy) | Not deprecated, but API access is restricted to accounts with active prior usage; new projects directed to 3.x. | [Google Gemini Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) | **Retain in pricing catalog (status: restricted_legacy); exclude from defaults** |
| **Google** | `gemini-2.5-pro` | **Restricted Legacy** | $1.25 (Legacy) | $10.00 (Legacy) | Rates apply to prompts $\le 200\text{k}$. Access restricted to prior active accounts. | [Google Gemini Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) | **Retain in pricing catalog (status: restricted_legacy); exclude from defaults** |
| **Google** | `gemini-1.5-flash` | **Retired** | $0.075 (Hist) | $0.30 (Hist) | Discontinued mid-2025. | [Google Gemini Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) | **Retain in pricing catalog only (status: retired); exclude from defaults** |
| **Google** | `gemini-1.5-pro` | **Retired** | $1.25 (Hist) | $5.00 (Hist) | Discontinued mid-2025. | [Google Gemini Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) | **Retain in pricing catalog only (status: retired); exclude from defaults** |
| **Ollama** | `llama3.2:1b`, `llama3.2`, `phi3`, `mistral` | **Active** (Local) | $0.0 | $0.0 | Local hardware execution; no external API charges. | Local Ollama Service | **Keep in default allowlist & pricing** |
| **Mock** | `mock-model` | **Active** (Internal) | N/A | N/A | Explicitly excluded from cloud financial accounting (`mock_excluded`). | Internal Test Double | **Keep as default testing model** |

---

## 3. Official Documentation Sources Consulted

1. **Anthropic Model Deprecations**: [https://platform.claude.com/docs/en/about-claude/model-deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) (Verified 2026-10-25)
2. **Anthropic Pricing Guide**: [https://platform.claude.com/docs/en/about-claude/pricing](https://platform.claude.com/docs/en/about-claude/pricing) (Verified 2026-10-25)
3. **Anthropic Models Overview**: [https://platform.claude.com/docs/en/models/overview](https://platform.claude.com/docs/en/models/overview) (Verified 2026-10-25)
4. **Google Gemini Developer API Pricing**: [https://ai.google.dev/pricing](https://ai.google.dev/pricing) (Verified 2026-10-25)
5. **Google Gemini API Models Documentation**: [https://ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models) (Verified 2026-10-25)
6. **Google Gemini Deprecations**: [https://ai.google.dev/gemini-api/docs/deprecations](https://ai.google.dev/gemini-api/docs/deprecations) (Verified 2026-10-25)

---

## 4. Issues Identified & Resolutions

1. **Confirmed Issue: Missing `mistral` Catalog Entry**
   - *Problem*: `app/config.py` permitted `mistral` by default, but `app/pricing/config.json` lacked an entry for `mistral`, which caused local Ollama requests using `mistral` to receive `calculation_status: "unknown_model"` rather than `free_tier_local`.
   - *Resolution*: Added `"mistral": { "provider": "ollama", "is_local": true, "status": "active", "input_cost_per_1m": "0.0", "output_cost_per_1m": "0.0", "notes": "Local inference has no external API charge." }` to `app/pricing/config.json`.
2. **Catalog Integrity Verification**:
   - Confirmed all active default models have HTTPS `source_url` attributes and ISO `verification_date` fields.
   - Confirmed Decimal arithmetic cleanly quantizes to 6 decimal places (`ROUND_HALF_UP`).
   - Confirmed unknown token usage yields `missing_usage` with `None` costs, never fabricated zero figures.

---

## 5. Verification & Test Suite Execution

### 5.1 New Dedicated Regression Tests (`tests/unit/test_model_catalog_audit.py`)
- `test_catalog_file_integrity_and_schema`: Verifies catalog JSON structure and version `"2026-10-v3"`.
- `test_all_default_allowed_models_have_valid_catalog_entries`: Asserts 100% of `settings.allowed_models` exist in `config.json` with status `"active"`.
- `test_retired_and_restricted_models_excluded_from_default_allowlist`: Confirms all 8 deprecated/restricted models are absent from default allowlist and present in historical catalog.
- `test_pricing_metadata_types_units_and_verification_dates`: Validates rates, HTTPS URLs, and dates.
- `test_unknown_token_counts_produce_none_costs_not_zero`: Ensures missing tokens remain `None`.
- `test_historical_pricing_records_remain_accurately_computable`: Verifies exact historical cost calculations.
- `test_default_models_routing_integrity`: Asserts active models route to their intended provider adapter.

### 5.2 Test Results Summary
- **Pytest Full Suite**: **223 passed in 10.87s** (0 failed, 0 errors).
- **Evaluation Runner (`scripts/run_evaluation.py --mode quick`)**:
  - Total Cases: 15
  - Executed: 14 (100.0% pass rate)
  - Skipped: 1 (`eval_15_live_ollama_optional`, requires live local Ollama)
  - Failed: 0
  - Duration: 853.98ms

---

## 6. Phase 9 Readiness Recommendation

- **Verdict**: **Pass**
- **Recommendation**: SafeRoute LLM Gateway's model catalog, provider routing precedence, and pricing calculations are completely verified against official provider documentation.
- The repository is fully ready to proceed to **Phase 9 (Dynamic Multi-Provider Failover & Streaming Responses)**.
