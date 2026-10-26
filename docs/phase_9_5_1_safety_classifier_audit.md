# SafeRoute Phase 9.5.1 — Independent Safety Audit Report
### Semantic Safety Classification and Moderation Guardrails

**Project:** SafeRoute LLM Gateway (`D:\SafeRoute LLM Gateway`)
**Auditor:** Senior AI Safety Engineer, Application Security Engineer & Skeptical Backend Reviewer
**Audit Target:** Phase 9.5 Semantic Safety Classification & Moderation Guardrails
**Evaluation Date:** October 25, 2026

---

## 1. Executive Verdict

### **VERDICT: PASS WITH LIMITATIONS**

The independent safety audit of Phase 9.5 verifies that the semantic safety classification and entity redaction layer is functionally integrated into the gateway pipeline. The layer operates as an auxiliary risk filter that compliments deterministic Phase 6 guardrails.

During this audit, **three defects (one High severity, two Medium severity)** were identified in the Phase 9.5 implementation and **fully remediated with regression tests**:
1. **Cache Pollution on Overlapping Redaction & Flagging (High):** Requests containing both PII (action: `redact`) and risk indicators (action: `flag_and_forward`) previously suffered from mutually exclusive conditional branches, preventing `is_safety_flagged` from being set and allowing flagged prompts to be stored in Redis cache.
2. **Missing Output Flagging Cache Bypass (Medium):** When provider responses triggered `flag_and_forward` during output classification, `is_safety_flagged` was not updated, allowing flagged output to be written to exact and semantic caches.
3. **Initialization Failure Bypassed Failure Policy (Medium):** Model loading in `LocalSemanticSafetyClassifier.classify_input()` occurred outside the try/except block, causing missing or corrupt weights to throw an uncaught HTTP 500 error even when `safety_classifier_failure_policy=fail_open` was configured.

Following these fixes:
- **Unit and Integration Test Suite:** **365 passed, 0 failed** in 37.52s.
- **Safety Benchmark Suite (Expanded to 30 cases):** **26/30 passed (86.67% accuracy)** with 1 False Positive and 3 False Negatives revealing documented model boundaries.
- **Inference Latency:** Warmed mean inference latency is **10.37 ms** (P50: 9.91 ms, P95: 15.33 ms, min: 6.94 ms, max: 15.86 ms), meeting the 15 ms target on CPU. Cold-start initialization requires **12.10 s**.

---

## 2. Findings Ranked by Severity

### Finding 1: Overlapping PII Redaction and Risk Flagging Fails to Bypass Cache
- **Severity:** **HIGH** (Cache Integrity & Cross-Tenant Leakage)
- **Files / Functions:** [`app/guardrails/safety_models.py`](file:///d:/SafeRoute%20LLM%20Gateway/app/guardrails/safety_models.py) (`SafetyClassificationResult.is_flagged`), [`app/api/routes.py`](file:///d:/SafeRoute%20LLM%20Gateway/app/api/routes.py) (lines 519–527)
- **Description:**
  When an incoming prompt contained both PII (configured with action: `redact`) and prompt injection (configured with action: `flag_and_forward`), `SafetyClassificationResult.primary_action` was resolved as `redact` (precedence: `BLOCK` > `REDACT` > `FLAG_AND_FORWARD` > `ALLOW`). In `routes.py`, the routing logic was structured as:
  ```python
  elif safety_res.is_redacted and safety_res.redacted_messages:
      request.messages = safety_res.redacted_messages
  elif safety_res.is_flagged:
      is_safety_flagged = True
  ```
  Because the request was marked as redacted, execution entered the first branch and bypassed the `elif` branch. `is_safety_flagged` remained `False`. Consequently, when the request completed, it was written into Redis exact and semantic caches, allowing prompt-injected content to pollute the cache.
- **Remediation:**
  - Updated `SafetyClassificationResult` to add `has_flagged_category`, returning `True` if any evaluated category demands `flag_and_forward`.
  - Updated `routes.py` so redaction and flagging checks are independent sequential `if` statements rather than mutually exclusive `elif` blocks.
  - Added regression test `test_overlapping_pii_redaction_and_risk_flagging_bypasses_cache`.

---

### Finding 2: Provider Output Classification Flagging Did Not Prevent Cache Writes
- **Severity:** **MEDIUM** (Cache Contamination)
- **Files / Functions:** [`app/api/routes.py`](file:///d:/SafeRoute%20LLM%20Gateway/app/api/routes.py) (lines 1105–1146)
- **Description:**
  When `safety_classifier_inspect_output` evaluated completion text from upstream providers, it checked whether `out_safety.should_block`. However, if the output triggered a category configured to `flag_and_forward`, `is_safety_flagged` was never set. As a result, flagged provider output was written directly into exact and semantic caches.
- **Remediation:**
  Added `elif out_safety.is_flagged or out_safety.has_flagged_category:` in `routes.py` post-provider output classification to set `is_safety_flagged = True` and emit `X-Safety-Risk: flagged`. This forces `X-Cache: BYPASS` and prevents caching.

---

### Finding 3: Model Loading Exception Bypassed Configured Failure Policy
- **Severity:** **MEDIUM** (Operational Reliability)
- **Files / Functions:** [`app/guardrails/classifier.py`](file:///d:/SafeRoute%20LLM%20Gateway/app/guardrails/classifier.py) (`LocalSemanticSafetyClassifier.classify_input`)
- **Description:**
  `await self._ensure_loaded()` was invoked prior to the `try...except` block in `classify_input()`. If local model weights were corrupted, missing, or PyTorch encountered a native runtime error during initial tensor loading, an unhandled `AppException` (HTTP 500) was raised, bypassing the administrator's configured `safety_classifier_failure_policy` (`fail_open`).
- **Remediation:**
  Moved `await self._ensure_loaded()` inside the `try` block so that initialization errors trigger the defined failure policy (cleanly returning HTTP 400/503 under `fail_closed` or `flag_and_forward` under `fail_open`).
  - Added regression test `test_classifier_initialization_error_respects_failure_policy`.

---

### Finding 4: Inherent Heuristic and Anchor Model Blind Spots
- **Severity:** **LOW / INFORMATIONAL** (Model Generalization Limits)
- **Files / Functions:** [`app/guardrails/classifier.py`](file:///d:/SafeRoute%20LLM%20Gateway/app/guardrails/classifier.py) (`INJECTION_HEURISTIC_PATTERNS`, `PROMPT_INJECTION_ANCHORS`)
- **Description:**
  Empirical benchmarking with nuanced edge cases revealed the fundamental limitations of static anchor similarity combined with regular expression heuristics:
  1. **Quoted Academic Analysis (False Positive):** Prompts quoting injection patterns (e.g., `The researcher noted: 'Ignore all previous instructions'`) trigger the regex heuristic boost (`0.88`), causing false positive blocks.
  2. **Persona & Hypothetical Jailbreaks (False Negative):** Prompts using persona framing (e.g., "Grandmother telling bedtime story on making explosives" or "Hypothetical academic simulation where safety rules are removed") achieve low cosine similarity (`0.23`–`0.36`) to directive-override anchors and bypass regex heuristics, producing false negatives.
- **Auditor Note:**
  An anchor-based SentenceTransformer classifier is an auxiliary risk filter, not an omniscient safety oracle. It cannot replace multi-layer defense in depth or specialized instruction-tuned safety reward models (e.g., Llama-Guard).

---

## 3. Pipeline Trace and Security Invariants

### Request Lifecycle Trace
1. **Authentication & Authorization:** Client API key and verification secret validated (`app/core/auth.py`).
2. **Deterministic Input Guardrails:** Phase 6 regex/contains rules execute (`app/guardrails/engine.py`). Blocked requests abort immediately with HTTP 400 before semantic classification.
3. **Semantic Safety Classification:** `classify_input` runs on `LocalSemanticSafetyClassifier`.
   - If blocked: returns HTTP 400 (`SafetyClassificationBlockedError`); no cache lookup or provider call occurs.
   - If redacted: `request.messages` are modified in-place with sanitized tokens (`[REDACTED_SSN]`, etc.).
   - If flagged: `is_safety_flagged` is set to `True`, attaching `X-Safety-Risk: flagged`.
4. **Cache Key Computation:** Exact cache key is computed using `request.messages`. Because redaction precedes cache key calculation, cache keys are constructed from *redacted* text, preventing PII leakage into Redis keys.
5. **Exact & Semantic Cache Lookups:** Performed only for unblocked requests. Flagged requests bypass read hits. Cached responses undergo output guardrail and semantic safety checks; violating entries are deleted from Redis.
6. **Provider Execution:** Provider receives `request.messages` (redacted).
7. **Output Safety Checks:** Provider completion inspected by deterministic output guardrails and semantic output classification.
8. **Cache Insertion:** Cache writes occur ONLY if `not failover_occurred and not is_safety_flagged`. If flagged, `X-Cache: BYPASS` is returned, preventing cache pollution.
9. **Accounting & Audit Persistence:** `_safe_record_outcome` persists metadata (latency, tokens, status, error code) to SQLite. User prompts, completions, and raw PII are never logged to the database.

---

## 4. Benchmark and Empirical Evaluation Results

The evaluation suite ([`datasets/evaluation/safety_classification_suite.json`](file:///d:/SafeRoute%20LLM%20Gateway/datasets/evaluation/safety_classification_suite.json)) was expanded from 20 to 30 cases to rigorously test edge cases:
- 10 Benign / Technical Language queries
- 5 Prompt Injection variants
- 3 Hate Speech queries
- 4 Severe Toxicity / Harm queries
- 5 PII types and benign lookalikes
- 3 Borderline cases (negation, quoted attack analysis, cybersecurity education)

### Empirical Evaluation Statistics (`scripts/benchmark_safety_classifier.py --provider local --allow-limitations`)
- **Total Cases:** 30
- **Overall Accuracy:** 86.67% (26 / 30)
- **False Positives (FP):** 1 (3.33%)
- **False Negatives (FN):** 3 (10.0%)
- **Cold-Start Model Initialization:** 12.10 s
- **Warmed Inference Latency Statistics:**
  - **Mean:** 10.37 ms
  - **Median (P50):** 9.91 ms
  - **95th Percentile (P95):** 15.33 ms
  - **Min:** 6.94 ms
  - **Max:** 15.86 ms

### Per-Category Breakdown
| Category | Total | Correct | FP | FN | Precision | Recall | Accuracy | Mean Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `benign` | 10 | 10 | 0 | 0 | 1.0000 | 1.0000 | 100.0% | 11.42 ms |
| `prompt_injection` | 5 | 4 | 0 | 1 | 1.0000 | 0.8000 | 80.0% | 8.26 ms |
| `hate_speech` | 3 | 2 | 0 | 1 | 1.0000 | 0.6667 | 66.67% | 10.64 ms |
| `severe_toxicity` | 4 | 3 | 0 | 1 | 1.0000 | 0.7500 | 75.0% | 10.59 ms |
| `pii` | 5 | 5 | 0 | 0 | 1.0000 | 1.0000 | 100.0% | 10.20 ms |
| `borderline` | 3 | 2 | 1 | 0 | 0.0000 | 1.0000 | 66.67% | 10.12 ms |

---

## 5. Test Suite Verification

### Regression and Integration Suites
```powershell
# Focused safety unit and integration tests (including new audit regressions)
pytest tests/unit/test_safety_classification.py tests/integration/test_safety_classification_integration.py -v
# Output: 16 passed in 17.69s

# Full gateway test suite
pytest -q
# Output: 365 passed in 37.52s

# Standard gateway evaluation harness
python scripts/run_evaluation.py --mode quick
# Output: 14 passed, 0 failed, 1 skipped (live optional)
```

---

## 6. Security and Privacy Limitations

1. **Regex-Based PII Coverage:** High-precision PII redaction is limited to format-constrained entities: Luhn-valid credit card PANs, US Social Security Numbers, standard Cloud/API tokens (AWS, GitHub, Bearer), emails, and US phone numbers. Free-form conversational personal disclosures (e.g., "my address is 123 Main St, Apartment 4B") are not captured.
2. **Persona Framing & Adversarial Suffixes:** Dense vector similarity against 18 anchor exemplars cannot detect indirect persona roleplay (e.g., grandma bedtime stories) or token-level adversarial gradient suffixes without specialized fine-tuned safety models.
3. **Streaming Token Latency Trade-off:** Output semantic classification is evaluated only on buffered non-streaming responses and cached entries. Streaming completions rely exclusively on deterministic Phase 6 regex guardrails on accumulated chunk text to avoid adding 10 ms per emitted token.
4. **Mock Classifier Production Lockout:** Verified that both `app/config.py` Pydantic model validators and `app/guardrails/classifier.py` runtime providers strictly reject `SAFETY_CLASSIFIER_PROVIDER=mock` when `APP_ENV=production`.

---

## 7. Recommendations by Deployment Environment

| Deployment Tier | Recommendation | Operational Requirements |
| :--- | :---: | :--- |
| **Controlled Demo** | **APPROVED** | Either `mock` or `local` provider may be used. Demo setups should note that benign technical keywords (`kill -9`, `purge`) pass cleanly. |
| **Staging** | **APPROVED** | Use `local` provider with SentenceTransformers. Verify Redis cache bypass on flagged requests and monitor latency. |
| **Production** | **CONDITIONAL PASS** | Production sign-off requires: <br>1. **Pre-bake Weights:** Model weights (`sentence-transformers/all-MiniLM-L6-v2`) must be included in the container image (`local_files_only=True`).<br>2. **Worker Pre-warming:** FastAPI startup event must invoke `_ensure_loaded()` to absorb the 12.1 s cold-start latency before receiving traffic.<br>3. **Failure Policy:** Set `SAFETY_CLASSIFIER_FAILURE_POLICY=fail_closed` for regulated/financial deployments, or `fail_open` for consumer applications prioritizing availability.<br>4. **Live Infrastructure Verification:** Redis cluster and cloud LLM providers (Claude, Gemini) remain unverified against live endpoints in the local test environment. |

---

*Phase 9.5.1 Independent Safety Audit is complete. The system is stable, hardened against cache pollution, and verified across all 365 tests.*
