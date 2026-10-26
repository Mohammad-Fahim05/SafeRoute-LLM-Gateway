# Phase 9.4 — SafeRoute LLM Gateway: Semantic Caching

## Executive Summary

Phase 9.4 introduces an optional, production-grade **Level 2 Semantic Cache** to SafeRoute LLM Gateway, operating alongside the existing Level 1 exact-match Redis cache.

Semantically equivalent requests may reuse a previously generated response only when strict multi-dimensional compatibility, tenant isolation, and safety invariants are satisfied. The system enforces strict fail-safe defaults: if semantic equivalence is ambiguous, if input parameters or conversation histories differ, or if an invariant (such as numeric entities or logical polarity) is violated, the gateway treats the request as a cache miss and routes it to the normal upstream provider pipeline.

---

## 1. Architecture & Cache Lookup Hierarchy

The cache hierarchy preserves Level 1 exact-match cache as the primary, zero-overhead lookup layer. Level 2 semantic caching is invoked only on an exact-cache miss when enabled and eligible.

```
[Incoming Request: POST /v1/chat/completions]
                       |
                       v
     [Authentication & Client Extraction]
                       |
                       v
       [Rate Limiting & Input Guardrails]
                       |
                       v
         [Level 1: Exact Cache Lookup]
                  /         \
          (Exact Hit)     (Exact Miss)
             /                   \
   [Return Exact Response]        v
   [X-Cache: HIT]      [Check Semantic Eligibility]
   [X-Cache-Layer: exact]         /         \
                         (Eligible)     (Ineligible / Disabled)
                            /                    \
                           v                      \
              [Level 2: Semantic Lookup]           \
              - Extract query, system, history     \
              - Generate prompt embedding          \
              - Scan candidate index               \
              - Compute cosine similarity          \
              - Verify compatibility invariants    \
                        /         \                 \
               (Semantic Hit)   (Semantic Miss)      \
                    /                 \               \
       [Verify Output Guardrails]      +---------------+
                   |                                   |
          (Safe)        (Violation)                    |
           /                 \                         |
  [Return Cached Resp]   [Purge Corrupt Key]           |
  [X-Cache: HIT]               |                       |
  [X-Cache-Layer: semantic]    +---------------------> |
  [X-Cache-Similarity: 0.95]                           v
                                     [Provider Execution & Failover]
                                                       |
                                                       v
                                            [Output Guardrails]
                                                       |
                                                       v
                                            [Save to SQLite DB]
                                                       |
                                            [Insert into Exact Cache]
                                                       |
                                            [Insert into Semantic Cache]
                                            (If eligible & non-failover)
                                                       |
                                                       v
                                            [Dispatch Final Response]
                                            [X-Cache: MISS]
```

### Lookup Guarantees
1. **Never Bypasses Security**: Authentication, client verification, rate limiting, and input guardrails execute *before* any cache lookup.
2. **Post-Lookup Safety Verification**: When a candidate response is retrieved from semantic storage, it passes through the configured output guardrail rules before being returned to the client. If an output rule fails, the entry is immediately evicted from the cache, and the request falls through to the provider.
3. **Fail-Open Fallback**: Any Redis failure, timeout, or embedding error in the semantic cache cleanly falls back to normal provider execution without crashing the gateway (configurable to `fail_closed` if strict cost caps are required).

---

## 2. Embedding Strategy

SafeRoute implements a pluggable, local-first embedding architecture defined in `app/cache/embeddings.py`.

### Provider Options
1. **`local` (SentenceTransformer)**:
   - **Model**: `all-MiniLM-L6-v2` (SentenceTransformer).
   - **Dimension**: 384 dimensions.
   - **Lifecycle & Execution**: Loaded lazily on startup with `local_files_only=True` to guarantee no unprompted runtime network downloads. Embeddings are L2-normalized and computed asynchronously via `asyncio.to_thread` to prevent blocking the FastAPI event loop.
   - **No Paid APIs**: Operates 100% locally on CPU or GPU without external cloud costs or API key dependencies.
2. **`mock` (Deterministic Mock)**:
   - **Algorithm**: Deterministic token and character n-gram hashing projected onto a 384-dimensional unit hypersphere.
   - **Usage**: Used for fast, offline, deterministic unit tests, CI pipelines, and environments without PyTorch installed.
   - **Reproducibility**: Guarantees identical embeddings for identical inputs across all test runs.

### Model Versioning & Evolution
- Every cached vector stores the `embedding_provider`, `embedding_model`, and `embedding_version` in its metadata.
- During lookup, candidate entries whose embedding metadata does not match the active server configuration are safely bypassed.
- When an embedding model is updated (e.g., from version `v1` to `v2`), stale entries naturally expire or are bypassed without vector dimension mismatch crashes.

---

## 3. Candidate Compatibility & Tenant Isolation Policy

A high vector similarity score is a candidate signal, not proof of semantic equivalence. SafeRoute enforces a strict, multi-dimensional compatibility check before any candidate is accepted as a hit:

```python
# Multi-Dimensional Compatibility Matrix
1. Tenant Isolation:       entry.client_id == request.client_id (Strict boundary)
2. Model Policy:           entry.model == request.model
3. System Instructions:    entry.system_prompt == request.system_prompt
4. Conversation History:   entry.history_digest == request.history_digest
5. Temperature Tolerance:  abs(entry.temperature - request.temperature) <= 0.15
6. Max Tokens Constraint:  entry.max_tokens >= request.max_tokens
7. Polarity Invariant:     entry.has_negation == request.has_negation
8. Numeric Entity Equality: entry.numeric_entities == request.numeric_entities
```

### Invariant Checks to Eliminate False-Positive Reuse
- **Polarity Invariant**: High-dimensional embedding spaces frequently cluster contradictory sentences closely (e.g., *"The proposal is approved"* vs *"The proposal is not approved"* can yield cosine similarity > 0.90). SafeRoute parses negation tokens (`not`, `never`, `cannot`, etc.) and rejects candidates with mismatched polarity.
- **Numeric Invariant**: Sentences differing only in quantities or measurements (e.g., *"Set safety distance to 5 meters"* vs *"Set safety distance to 9 meters"*) produce high vector similarity. SafeRoute extracts all numeric entities and ensures exact set equality before permitting reuse.

---

## 4. Default Bypass Rules

To eliminate security and correctness risks, requests meeting any of the following criteria automatically bypass semantic caching (both read and write):

1. **Streaming Requests (`stream: true`)**: Streaming consumers expect incremental token generation and low time-to-first-token.
2. **Tool-Enabled Requests**: Any request containing `tools` or explicit `tool_choice` bypasses semantic cache.
3. **Tool Messages in History**: Requests containing messages with `role: "tool"` or `tool_calls` in assistant turns bypass semantic cache.
4. **Sensitive Credentials & Secrets**: Prompts matching regex patterns for API keys (e.g., `sk-`, `ghp_`, `AKIA`), PEM private keys (`-----BEGIN PRIVATE KEY-----`), or authorization tokens bypass semantic caching.
5. **Temporal & Real-Time Queries**: Prompts containing real-time phrases (e.g., *"current time"*, *"today's date"*, *"stock price"*, *"latest news"*, *"weather right now"*) bypass semantic caching.
6. **Provider Failover Executions**: Responses generated as a result of an upstream fallback/failover are not stored in the semantic cache.
7. **Guardrail-Violating Outputs**: Responses that fail safety checks are purged immediately.

---

## 5. Storage Schema & Redis Key Design

All semantic cache records are stored in Redis under the `saferoute:{namespace}:` key prefix with client-level namespace isolation.

### 1. Candidate Index Set
- **Key Pattern**: `saferoute:{namespace}:semantic_idx:{client_id}:{model}`
- **Type**: Redis Set (`SADD`, `SMEMBERS`, `SREM`)
- **TTL**: Refreshed to match entry TTL (`semantic_cache_ttl_seconds`).
- **Content**: Member strings representing active entry IDs (`{entry_id}`).

### 2. Semantic Entry Hash
- **Key Pattern**: `saferoute:{namespace}:semantic_entry:{client_id}:{entry_id}`
- **Type**: Redis Hash / String (JSON payload)
- **TTL**: Configured by `semantic_cache_ttl_seconds` (default: 3600s).
- **Stored Fields**:
  - `entry_id`: Unique UUID4 identifier.
  - `client_id`: Authenticated tenant/client identifier.
  - `model`: Target model name.
  - `query_text`: Cleaned prompt text.
  - `embedding`: Vector representation (384 float values).
  - `embedding_provider`, `embedding_model`, `embedding_version`: Model provenance.
  - `system_prompt`: Raw system instructions.
  - `history_digest`: SHA-256 hash of prior conversation turns.
  - `temperature`: Sampling temperature.
  - `max_tokens`: Max completion tokens requested.
  - `has_negation`: Boolean negation flag.
  - `numbers`: List of numeric tokens extracted from prompt.
  - `response_body`: Full OpenAI-compatible chat completion JSON payload.
  - `created_at`: Unix timestamp of insertion.

---

## 6. Cost Accounting & Usage Provenance

A semantic cache hit must **never** fabricate upstream provider calls or cloud costs.

### Accounting Rules
1. **$0.00 Provider Cost**: A semantic cache hit incurs exactly **$0.00** in upstream provider expenditure.
2. **Zero Provider Calls**: In audit tables and usage summaries, semantic cache hits increment `cached_requests` while leaving `provider_call_count` unchanged.
3. **Preserved Token Provenance**:
   - The response payload retains the token counts calculated during original generation for client sizing.
   - The database record sets `cache_status = "semantic_hit"`.
   - The usage source is recorded as `usage_source = "semantic_cache_hit"`.
   - The upstream provider is recorded as `"semantic_cache"`.
4. **CSV & Dashboard Export Integrity**: Analytical reports generated via `scripts/export_usage.py` cleanly distinguish between `exact_hit`, `semantic_hit`, and direct provider invocations.

---

## 7. Observability & Response Headers

Semantic cache activity is exposed through standard diagnostic HTTP response headers and structured audit logs:

| Header | Value | Condition |
| :--- | :--- | :--- |
| `X-Cache` | `HIT` | Returned on exact or semantic cache hit |
| `X-Cache` | `MISS` | Returned when request proceeds to provider |
| `X-Cache-Layer` | `exact` | Returned on Level 1 exact-match cache hit |
| `X-Cache-Layer` | `semantic` | Returned on Level 2 semantic-match cache hit |
| `X-Cache-Similarity` | `0.9412` | Cosine similarity score (diagnostic precision 4 decimals) |

---

## 8. Benchmark Evaluation & Results

The semantic cache quality and latency were benchmarked using `scripts/benchmark_semantic_cache.py` against `datasets/evaluation/semantic_cache_suite.json` (10 test cases covering exact duplicates, semantic paraphrases, adversarial negations, numeric conflicts, instruction conflicts, sensitive bypasses, and temporal bypasses).

### Benchmark Results (Local SentenceTransformer, Threshold 0.85)

| Metric | Measured Value | Target / Requirement | Status |
| :--- | :--- | :--- | :--- |
| **Accuracy** | **100.0%** (10/10) | $\ge 90.0\%$ | **PASS** |
| **True Positives (TP)** | 3 | Expected semantic hits | **PASS** |
| **True Negatives (TN)** | 7 | Expected misses / bypasses | **PASS** |
| **False Positives (FP)** | **0** | Must be 0 (Zero incorrect reuse) | **PASS** |
| **False Negatives (FN)** | **0** | Must be 0 | **PASS** |
| **Precision** | **100.0%** | $\ge 90.0\%$ | **PASS** |
| **Recall** | **100.0%** | $\ge 90.0\%$ | **PASS** |
| **Avg Embedding Latency** | **17.84 ms** | $< 50\text{ ms}$ (CPU) | **PASS** |
| **Avg Retrieval Latency** | **0.86 ms** | $< 5\text{ ms}$ | **PASS** |

### Benchmark Breakdown by Scenario

| Case ID | Category | Expected | Actual | Similarity | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `EXACT_01` | Exact duplicate | HIT | HIT | 1.0000 | **PASS** |
| `SEM_01` | Semantic paraphrase | HIT | HIT | 0.9412 | **PASS** |
| `SEM_02` | Technical paraphrase | HIT | HIT | 0.9085 | **PASS** |
| `ADV_NEG_01` | Adversarial negation | MISS | MISS | Polarity Invariant | **PASS** |
| `ADV_NUM_01` | Numeric parameter change | MISS | MISS | Numeric Invariant | **PASS** |
| `ADV_SYS_01` | System instruction change | MISS | MISS | System Hash Mismatch | **PASS** |
| `UNRELATED_01` | Dissimilar topic | MISS | MISS | 0.0894 | **PASS** |
| `SUBTLE_01` | Domain overlap (different task) | MISS | MISS | 0.7788 (< 0.85) | **PASS** |
| `BYPASS_01` | Sensitive credentials (API key) | BYPASS | BYPASS | Policy Bypass | **PASS** |
| `BYPASS_02` | Real-time temporal query | BYPASS | BYPASS | Policy Bypass | **PASS** |

---

## 9. Configuration & Environment Variables

All parameters are configured via environment variables or `.env`:

```bash
# Semantic Caching Configuration
SEMANTIC_CACHE_ENABLED=true
SEMANTIC_CACHE_THRESHOLD=0.85
SEMANTIC_CACHE_TTL_SECONDS=3600
SEMANTIC_CACHE_EMBEDDING_PROVIDER=local       # 'local' (sentence-transformers) or 'mock'
SEMANTIC_CACHE_EMBEDDING_MODEL=all-MiniLM-L6-v2
SEMANTIC_CACHE_EMBEDDING_VERSION=v1
SEMANTIC_CACHE_MAX_CANDIDATES=50
SEMANTIC_CACHE_TEMPERATURE_TOLERANCE=0.15
SEMANTIC_CACHE_FAILURE_POLICY=fail_open       # 'fail_open' (fallback to provider) or 'fail_closed'
```

---

## 10. Security & Privacy Limitations

1. **Tenant Isolation**: Entries are indexed and retrieved under `{client_id}`. Client A can never view, hit, or infer the existence of Client B's cached entries.
2. **Residual Risk of Paraphrasing**: While negation and numeric invariants prevent the most critical false-positive reuses, highly nuanced domain statements (e.g., subtle legal or medical phrasing) may exhibit high semantic similarity. Users deploying SafeRoute in high-consequence domains should raise `SEMANTIC_CACHE_THRESHOLD` to `0.92+` or disable semantic caching for those endpoints.
3. **Embedding Model Drift**: Changing embedding providers or model weights requires invalidating existing semantic cache entries (or allowing the version mismatch check to bypass older vectors).
