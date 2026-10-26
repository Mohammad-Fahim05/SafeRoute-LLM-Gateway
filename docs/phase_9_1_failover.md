# Phase 9.1 Multi-Provider Failover Implementation & Verification Report

**Project**: SafeRoute LLM Gateway (`D:\SafeRoute LLM Gateway`)
**Phase**: Phase 9.1 (Multi-Provider Failover for Non-Streaming Requests)
**Author / Engineer**: Senior Backend Engineer & Reliability Specialist
**Date**: October 25, 2026
**Status**: **Pass** (All 20 required scenarios tested and validated; full regression suite passing)

> [!NOTE]
> **Streaming Notice**: Streaming requests (`stream: true`) are strictly out of scope for Phase 9.1 and will be implemented in Phase 9.2. In this phase, streaming requests are rejected or bypass caching and failover as per Phase 1 design.

---

## 1. Executive Summary

Phase 9.1 introduces a configurable, deterministic, and observable multi-provider failover system to SafeRoute LLM Gateway for non-streaming chat completion requests.

Key accomplishments:
1. **Preserved Complete Security & Validation Pipeline**: Authentication, Pydantic schema validation, model allowlists, rate limiting, and input guardrails are strictly enforced *before* any provider call is attempted.
2. **Explicit Failure Classification**: Transient, retryable errors (timeouts, rate limits with bounded `Retry-After`, upstream 5xx errors, network connection drops, malformed JSON) trigger failover to configured fallbacks; client errors (401/403 credentials, 400 schema, 429 gateway rate limit, input/output guardrail violations) halt immediately without failover.
3. **Model Catalog & Lifecycle Protection**: Fallback models are validated against the active model allowlist and pricing catalog to reject retired or deprecated models (such as `claude-3-7-sonnet-20250219`).
4. **Duplicate Work, Billing Integrity & Cache Isolation**: The gateway never fabricates token usage or costs for failed attempts. Responses served via fallback are marked with `X-Cache: BYPASS` and are never cached under the originally requested model's key, preventing cross-model response contamination.
5. **Observability & Persistence**: Durably records request sequence attempts, latency per attempt, failure categories, actual serving provider/model, and failover occurrence in SQLite and structured headers (`X-Serving-Provider`, `X-Serving-Model`, `X-Requested-Model`, `X-Failover-Occurred`, `X-Failover-Attempts`).
6. **Full Test Coverage**: Implemented 26 comprehensive unit and integration tests covering all 20 required scenarios. Full suite of **249 tests passing in 9.56s**. Quick evaluation suite running with 100% pass rate.

---

## 2. Architecture and Request Flow

The multi-provider failover mechanism integrates seamlessly at Step 7 of the request lifecycle, ensuring all upstream gates remain intact.

```mermaid
flowchart TD
    A["Incoming Request: /v1/chat/completions"] --> B["1. API Key Authentication (verify_api_key)"]
    B -->|Unauthorized| ERR1["401 Unauthorized (No Failover)"]
    B -->|Valid| C["2. Schema & Model Allowlist Validation"]
    C -->|Invalid Model / Extra Fields| ERR2["400/422 Error (No Failover)"]
    C -->|Valid| D["3. Redis Rate Limiter Check"]
    D -->|Quota Exceeded| ERR3["429 Rate Limit Exceeded (No Failover)"]
    D -->|Quota OK| E["4. Input Safety Guardrails Inspection"]
    E -->|Blocked Prompt| ERR4["400 Input Guardrail Blocked (No Failover)"]
    E -->|Passed| F["5. Redis Exact-Match Cache Lookup (Original Model)"]
    F -->|Cache Hit| G["Return Cached Response (X-Cache: HIT, Failover: false)"]
    F -->|Cache Miss| H["6. Failover Execution Orchestrator"]

    subgraph Failover Loop
        H --> I["Attempt 1: Primary Model (e.g. Claude)"]
        I -->|Success| M["7. Output Safety Guardrails"]
        I -->|Transient Failure (5xx, 429, Timeout)| J{"Eligible & Remaining Attempts?"}
        J -->|No / Ineligible (e.g. 401)| K["Return Safe Normalized Error (No More Retries)"]
        J -->|Yes| L["Attempt 2: Fallback Model (e.g. Gemini / Mock)"]
        L -->|Success| M
        L -->|Failure| J
    end

    M -->|Output Blocked| ERR5["502 Output Guardrail Blocked (No Failover)"]
    M -->|Passed| N{"Was Fallback Used?"}
    N -->|No (Primary Succeeded)| O["Store in Redis Cache for Primary Model (X-Cache: MISS)"]
    N -->|Yes (Fallback Succeeded)| P["Bypass Cache Write (X-Cache: BYPASS) to Prevent Cross-Model Pollution"]
    O --> Q["8. Record Outcome in SQLite DB & Return Response with Observability Headers"]
    P --> Q
```

---

## 3. Failover Decision Rules & Classification Policy

Failover is attempted **only** when all prerequisite validation checks have succeeded and the failure is classified as transient.

### Eligible Failures (Permit Failover)
| Failure Type | Error / Exception Class | Trigger Condition | Failover Action |
| :--- | :--- | :--- | :--- |
| **Connection Timeout** | `ProviderTimeoutError`, `asyncio.TimeoutError`, `httpx.TimeoutException` | Provider takes longer than configured attempt timeout | Switches to next fallback within remaining budget |
| **Provider Overload / 429** | `ProviderRateLimitError` | Upstream provider returns HTTP 429 | Respects `Retry-After` if within deadline cap; then attempts fallback |
| **Upstream 5xx Outage** | `ProviderError` | Upstream provider returns HTTP 500, 502, 503, 504 | Switches to next fallback |
| **Malformed Response** | `ProviderMalformedResponseError` | Unparseable or corrupted JSON payload | Switches to next fallback |
| **Network Drop** | `httpx.ConnectError`, `httpx.NetworkError` | TCP connection refused or reset before response headers | Switches to next fallback |

### Ineligible Failures (Strictly Reject / Halt Immediately)
| Failure Type | Exception Class | Reason for Rejection |
| :--- | :--- | :--- |
| **Authentication / Keys** | `ProviderAuthenticationError`, `AuthenticationError` | Bad credentials or missing keys are permanent errors; retrying another provider or model masks configuration mistakes |
| **Client Schema Errors** | `InvalidModelError`, `UnsupportedParameterError`, `PayloadTooLargeError` | Request payload is malformed or invalid |
| **Client Rate Limiting** | `RateLimitExceededError` | Client has exceeded their assigned gateway quota |
| **Safety Guardrail Block** | `InputGuardrailBlockedError`, `OutputGuardrailBlockedError` | Safety policy violation; must never be bypassed by switching providers |
| **Disallowed / Retired Models** | `InvalidModelError` | Candidate models not in `allowed_models` or marked `retired` in catalog are skipped |
| **Unclassified Errors** | Generic `Exception` | Unknown errors default to fail-safe rejection |

---

## 4. Configuration and Safe Defaults

Configuration follows existing SafeRoute conventions via environment variables in `app/config.py`:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `FAILOVER_ENABLED` | `bool` | `false` | Master toggle. Conservative default preserves existing single-provider routing. |
| `FAILOVER_MAX_ATTEMPTS` | `int` | `3` | Maximum total attempts (initial primary + fallbacks) per request. Must be $\ge 1$. |
| `FAILOVER_TIMEOUT_BUDGET_SECONDS` | `float` | `15.0` | Global deadline budget across all attempts. Must be $> 0$. |
| `FAILOVER_RETRY_DELAY_SECONDS` | `float` | `0.5` | Base pause between attempts if budget permits. |
| `FAILOVER_MAX_RETRY_DELAY_SECONDS` | `float` | `5.0` | Maximum ceiling for respecting `Retry-After` upstream hints. |
| `FAILOVER_FALLBACK_MODELS` | `dict` / `json` | `{}` | Mapping from requested model to ordered list of fallback models. |
| `FAILOVER_ELIGIBLE_STATUS_CODES` | `list[int]` | `[429, 500, 502, 503, 504]` | HTTP status codes eligible for failover. |
| `FAILOVER_ELIGIBLE_ERROR_CODES` | `list[str]` | `["gateway_timeout", "provider_error", ...]` | Normalized error codes eligible for failover. |

### Per-Request Failover Control
Callers can override the global failover policy per request without breaking OpenAI compatibility:
- **HTTP Header**: `X-Allow-Failover: false` or `X-Allow-Failover: true`.
- **JSON Request Body**: `"allow_failover": false` or `true` in `ChatCompletionRequest`.

---

## 5. Billing Integrity, Hidden Costs, and Cache Isolation

### Preventing Duplicate Work and Billing Uncertainty
When an upstream provider call times out or drops the connection, the provider may have processed the prompt and accrued compute charges even though SafeRoute never received the completion tokens.

To prevent hidden costs and dishonest accounting:
1. **No Token Fabrication**: SafeRoute records token counts **only** from the actual serving provider. Failed attempts are recorded with `input_tokens: None`, `output_tokens: None`.
2. **Deterministic Spending Accounting**: The cost calculation engine evaluates only known tokens. If tokens are missing or provider calculation is uncertain, `calculation_status: "missing_usage"` or `"mock_excluded"` is set.
3. **Explicit Serving Attribution**: The returned completion response always reflects the actual model that generated the text in both `response.model` and headers.
4. **No Infinite Retries**: Bounded by `FAILOVER_MAX_ATTEMPTS` and `FAILOVER_TIMEOUT_BUDGET_SECONDS`.

### Cache Isolation
- Cache keys include `client_id`, `provider_name`, and requested `model`.
- When failover occurs and a fallback model serves the request, SafeRoute sets `X-Cache: BYPASS` and **does not** write the fallback response to the primary model's cache key.
- This ensures that a subsequent request for `claude-sonnet-4-6` will never mistakenly return cached text produced by `gemini-3.8-flash`.

---

## 6. Observability Fields

### HTTP Response Headers
| Header | Example Value | Description |
| :--- | :--- | :--- |
| `X-Serving-Provider` | `gemini` | The provider adapter that successfully completed the request. |
| `X-Serving-Model` | `gemini-3.8-flash` | The specific model identifier that generated the completion. |
| `X-Requested-Model` | `claude-sonnet-4-6` | The original model requested by the client. |
| `X-Failover-Occurred` | `true` | Boolean flag indicating whether failover was triggered. |
| `X-Failover-Attempts` | `2` | Total number of provider attempts executed. |
| `X-Cache` | `BYPASS` | Cache state (`HIT`, `MISS`, `BYPASS`, `DISABLED`, `ERROR`). |
| `X-Request-ID` | `req_1234567890abcdef` | Traceable request correlation ID. |

### Database Persistence (`request_records` table)
Extended schema with backward-compatible SQLite migration:
- `attempts_count`: Integer count of attempts executed (default 1).
- `failover_occurred`: Boolean flag indicating whether fallback was used (default 0).
- `attempt_sequence`: JSON array storing the step-by-step audit trail:
  ```json
  [
    {"attempt": 1, "provider": "claude", "model": "claude-sonnet-4-6", "success": false, "failure_category": "timeout", "latency_ms": 5002.1},
    {"attempt": 2, "provider": "gemini", "model": "gemini-3.8-flash", "success": true, "latency_ms": 420.5}
  ]
  ```

---

## 7. Automated Test Verification

All 20 required scenarios were implemented and validated using automated tests:

| Scenario # | Description | Test Name / Location | Result |
| :--- | :--- | :--- | :--- |
| **1** | Failover disabled preserves single-provider behavior | `test_failover_disabled_preserves_single_provider_behavior` | **PASS** |
| **2** | Primary succeeds without fallback attempt | `test_primary_succeeds_without_fallback_attempt` | **PASS** |
| **3** | Eligible primary failure succeeds through fallback | `test_eligible_primary_failure_succeeds_through_fallback` | **PASS** |
| **4** | All providers fail and gateway returns safe error | `test_all_providers_fail_returns_safe_error` | **PASS** |
| **5** | Auth failures (client and provider) do not failover | `test_authentication_failures_do_not_trigger_failover` | **PASS** |
| **6** | Invalid requests & schema errors do not failover | `test_invalid_requests_do_not_trigger_failover` | **PASS** |
| **7** | Guardrail rejections do not trigger failover | `test_input_guardrail_rejections_do_not_trigger_failover` | **PASS** |
| **8** | Disallowed & retired fallback models are skipped | `test_disallowed_and_retired_fallback_models_are_skipped` | **PASS** |
| **9** | Attempt limits are strictly respected | `test_attempt_limits_are_strictly_respected` | **PASS** |
| **10** | Request deadlines prevent unbounded retries | `test_request_deadlines_prevent_unbounded_retries` | **PASS** |
| **11** | Retry hints are handled within configured limits | `test_retry_hints_handled_within_limits` | **PASS** |
| **12** | Response metadata identifies actual serving model | `test_final_provider_model_metadata_identifies_serving_model` | **PASS** |
| **13** | Usage & cost fields preserve unknown values | `test_failed_attempts_do_not_fabricate_billing_data` | **PASS** |
| **14** | Partial/uncertain failures do not fabricate billing | `test_failed_attempts_do_not_fabricate_billing_data` | **PASS** |
| **15** | Request IDs and sanitized logs remain correct | `test_request_id_preserved_across_failover` | **PASS** |
| **16** | Cache isolation and fallback cache semantics | `test_cache_isolation_and_fallback_semantics` | **PASS** |
| **17** | Rate limiting is not bypassed by fallback | `test_rate_limiting_not_bypassed_by_fallback` | **PASS** |
| **18** | Output guardrails still apply to fallback responses | `test_output_guardrails_apply_to_fallback_responses` | **PASS** |
| **19** | Concurrent requests do not leak routing state | `test_concurrent_requests_independent_routing` | **PASS** |
| **20** | Request-level overrides disable failover | `test_request_header_disables_failover_when_globally_enabled` | **PASS** |

### Execution Commands & Outputs
```bash
# Failover unit & integration suite
pytest tests/unit/test_failover.py tests/integration/test_failover_integration.py -v
# Output: 26 passed in 1.64s

# Full gateway test suite
pytest -q
# Output: 249 passed in 9.56s

# Quick evaluation framework
python scripts/run_evaluation.py --mode quick
# Output: 14 passed, 1 skipped (live external service), 0 failed (100% pass rate)
```

---

## 8. Known Limitations & Future Work

1. **Non-Streaming Only**: Phase 9.1 strictly implements failover for non-streaming requests. Streaming chunk failover requires buffering headers before transmission and is deferred to Phase 9.2.
2. **Provider-Side Unreported Usage**: Upstream providers do not expose billing APIs for timed-out HTTP connections where inference began but the TCP connection terminated prematurely. SafeRoute documents this limitation and avoids guessing token counts.
3. **Static Routing vs Dynamic Health Scoring**: Fallback order is deterministic and configured via settings rather than dynamic background health probes. Circuit breakers and background health workers can be introduced in a future reliability phase.

---

## 9. Phase 9.1.1 Safety Review & Hardening

Following the Phase 9.1 implementation, a formal reliability and safety review audited the three critical failover areas:

### 1. Global vs Per-Request Failover Controls & Precedence
- **Precedence Hierarchy**:
  1. `X-Allow-Failover` HTTP Header (Highest priority). Values are strictly validated: `"true"`, `"1"`, `"yes"`, `"enabled"` enable failover; `"false"`, `"0"`, `"no"`, `"disabled"` disable failover. Unrecognized/malformed values immediately return **HTTP 400 `invalid_request`**.
  2. `allow_failover` JSON request body attribute (Medium priority).
  3. `FAILOVER_ENABLED` environment configuration (Baseline default).
- **Security Isolation**: Even when failover is enabled via per-request override while `FAILOVER_ENABLED=false`, security gates (API key authentication, model allowlist, max tokens/message limits, client rate limiting, and input guardrails) run **before** provider routing. A per-request setting can never bypass security controls.
- **Regression Tests Added**: Scenario 21 (`test_conflicting_settings_precedence`) and Scenario 22 (`test_malformed_failover_header_returns_400`).

### 2. Provider Rate Limits vs Gateway Rate Limits
- **Gateway Rate Limiting Isolation**: SafeRoute's client rate limits (`RateLimitExceededError`, HTTP 429) and limiter outages (`RateLimiterUnavailableError`, HTTP 503) are verified at Step 3 of the request pipeline. They are classified as `"ineligible_gateway_rate_limit"` and immediately return HTTP 429 / 503 to the client with `Retry-After` headers without ever triggering provider failover.
- **Provider Rate Limiting Bounded Failover**: Upstream provider 429 errors (`ProviderRateLimitError` or `httpx.HTTPStatusError` with status 429) are classified as eligible `"rate_limit"`. Upstream `Retry-After` headers are extracted and respected up to `FAILOVER_MAX_RETRY_DELAY_SECONDS`, pausing before safely attempting the next fallback provider within the global timeout budget.
- **Regression Tests Added**: Scenario 23 (`test_gateway_rate_limit_never_triggers_provider_failover`), unit tests for `RateLimitExceededError` and `httpx.HTTPStatusError` (429).

### 3. Mock-Provider Fallback Restrictions
- **Production Guardrail**: In production environments (`APP_ENV=production`), `validate_fallback_model` strictly rejects any mock candidate (`mock-*` or provider `mock`) if the originally requested model was a real AI model (`claude-*`, `gemini-*`, `llama*`, `phi*`, etc.). This guarantees production callers will never receive synthetic mock completions during cloud provider outages.
- **Non-Production Safe Default**: In non-production environments, mock fallback for real models is disabled by default via `FAILOVER_ALLOW_MOCK_FALLBACK=false`. It can only be enabled via explicit configuration opt-in.
- **Preserved Test Utility**: Mock-to-mock fallbacks (e.g., `mock-error` -> `mock-model`) remain 100% permitted in all environments, preserving automated test suites.
- **Configuration Update**: Updated `.env.example` to remove `mock-model` from cloud provider fallback chains, specifying clean cloud-to-cloud mapping (`claude-sonnet-4-6` <-> `gemini-3.8-flash`).
- **Regression Tests Added**: Scenario 24 (`test_production_rejects_mock_fallback_for_real_cloud_model`), unit tests for mock restrictions across production, strict dev, and opt-in configurations.

### Verification Results
- **Full Test Suite**: **253 passed in 10.98s** (`pytest -q`).
- **Evaluation Suite**: 14 passed, 1 skipped, 0 failed (100% pass rate).
- **Status**: Verified safe and ready for Phase 9.2 (Streaming Failover).
