# SafeRoute LLM Gateway — Technical Architecture & Design Decisions

This document details the architectural principles, trade-offs, and design decisions underpinning the SafeRoute LLM Gateway.

---

## 1. System Topology & Core Components

SafeRoute is a secure, high-performance orchestration gateway and reverse proxy positioned between client applications and upstream AI model backends.

```
                          [ Client Application ]
                                    |
                                    | HTTPS / SSE (Bearer Token)
                                    v
                     +------------------------------+
                     |   FastAPI Gateway Boundary   |
                     |  - Request-ID Assignment     |
                     |  - Payload Size Check (<1MB) |
                     |  - CORS & Security Headers   |
                     +------------------------------+
                                    |
                                    v
                     +------------------------------+
                     | HMAC-SHA256 Auth & Limiter   |
                     |  - Constant-time verification|
                     |  - Redis Atomic Fixed-Window |
                     +------------------------------+
                                    |
                     +--------------+---------------+
                     |                              |
                     v                              v
      +----------------------------+  +----------------------------+
      |  Input Safety Guardrails   |  |   Exact / Semantic Cache   |
      |  - Heuristic Regex Filter  |  |  - Redis SHA-256 Exact     |
      |  - Prompt Injection Probe  |  |  - Embedding Similarity    |
      +----------------------------+  +----------------------------+
                     |                              |
                     | (Cache Miss / Ineligible)    | (Cache Hit)
                     v                              |
      +----------------------------+                |
      | Upstream Provider Routing  |                |
      |  - Local Ollama Engine     |                |
      |  - Fallback / Failover     |                |
      |  - Deterministic Mock      |                |
      +----------------------------+                |
                     |                              |
                     +--------------+---------------+
                                    |
                                    v
                     +------------------------------+
                     | Output Guardrails & Masking  |
                     |  - PII Detection & Redaction |
                     |  - Cache Entry Storage       |
                     +------------------------------+
                                    |
                     +--------------+---------------+
                     |                              |
                     v                              v
      +----------------------------+  +----------------------------+
      |  SQLite WAL Persistence    |  |  Prometheus Observability  |
      |  - Usage & Token Audit Log |  |  - Request Counts & P95    |
      |  - Versioned Pricing Engine|  |  - Active Stream Gauges    |
      +----------------------------+  +----------------------------+
```

---

## 2. Deep-Dive Design Decisions

### 2.1 Why HMAC-Based Authentication Is Used
- **Vulnerability of Plaintext Secrets:** Traditional API key architectures store plaintext keys or unsalted hashes in databases. If database read privileges are compromised, all keys are exposed.
- **HMAC-SHA256 Hash Verification:** SafeRoute requires an application `AUTH_SECRET`. Client API keys follow the format `gw_<prefix>_<random_secret>`. When a request arrives with `Authorization: Bearer <key>`, the gateway computes an HMAC-SHA256 signature using the server secret and verifies the client signature using `hmac.compare_digest()`.
- **Constant-Time Comparison:** The use of `hmac.compare_digest()` prevents timing side-channel attacks where an attacker could deduce valid key bytes by measuring microsecond differences in early string termination.
- **Key Prefixing & Redaction:** Every key has a public prefix (used for client identity lookup in SQLite) and a secret suffix. Loggers, telemetry, and error handlers only ever record the redacted key (e.g., `gw_test_YbW...M`), completely eliminating credential exposure in stdout or traces.

### 2.2 Redis Failure Policy: Configurable Fail-Open vs. Fail-Closed
- **Cache Failure Policy (Fail-Open):** When Redis is down or unreachable, the caching layer logs a warning and gracefully degrades to upstream inference (`cache_status: OUTAGE`). A cache outage must never bring down core application inference.
- **Rate Limiter Failure Policy (Configurable):**
  - In *standard development and internal deployments*, the rate limiter operates **fail-open** (`RATE_LIMIT_FAIL_OPEN=true`), allowing business continuity during local Redis maintenance.
  - In *mission-critical enterprise deployments*, the rate limiter can be set to **fail-closed** (`RATE_LIMIT_FAIL_OPEN=false`), rejecting requests with HTTP 503 or 429 when limits cannot be guaranteed, preventing runaway API bills from unthrottled clients.

### 2.3 Exact-Match vs. Semantic Caching
SafeRoute employs a tiered caching strategy:
1. **Exact-Match Caching (Redis SHA-256):**
   - **Mechanism:** Computes a deterministic SHA-256 hash across `client_id`, `model`, `temperature`, `system_prompt`, `user_messages`, and `tools`.
   - **Performance:** Sub-millisecond Redis key lookup (~1ms).
   - **Guarantees:** 100% deterministic correctness. Zero risk of semantic drift or inappropriate answer reuse.
2. **Semantic Caching (Vector Similarity):**
   - **Mechanism:** Encodes incoming user prompts into high-dimensional vector embeddings and computes cosine similarity against historical query vectors within the client's isolated partition.
   - **Threshold Safety Gate:** Configured similarity threshold (default `0.92`).
   - **Numeric & Entity Boundary Guard:** Prompts containing distinct entity numbers (e.g., "delete user 5" vs. "delete user 6") or differing imperatives are explicitly flagged as incompatible candidates, preventing cross-entity contamination.
   - **Tenant Isolation:** Cache vectors are partitioned strictly by `client_id`. Client A can never match or retrieve vectors generated by Client B under any circumstances.

### 2.4 Client Isolation & Multi-Tenant Boundaries
SafeRoute enforces strict tenant isolation across every layer:
1. **API Layer:** Client identity is authenticated at the gateway entry point. Non-admin clients (`role: client`) can only view their own usage history, requests, and costs. Admin clients (`role: admin`) have access to management endpoints.
2. **Cache Layer:** Cache keys are prefixed with `tenant:<client_id>:`. Even if two clients submit the exact same prompt, they map to completely separate Redis keys and separate vector index partitions.
3. **Audit Log Layer:** SQLite usage records tag every entry with `client_id`. Filtering queries strictly enforce `WHERE client_id = :authenticated_client_id` for non-admin callers.

### 2.5 SQLite: Scope Suitability & PostgreSQL Migration Path
- **Why SQLite for the Current Gateway Scope:**
  - **Zero Deployment Overhead:** Embedded single-file database (`data/saferoute.db`) requiring no external database daemon, zero cloud provisioning, and instantaneous local startup.
  - **Write-Ahead Logging (WAL Mode):** Enabled via `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=15000;`. Under WAL mode, readers do not block writers and writers do not block readers. Reads execute concurrently with zero lock contention.
  - **Performance:** Handles thousands of read queries per second and sustained write throughput of 50–100 write transactions/sec with microsecond disk I/O.
- **PostgreSQL Migration Path:**
  - **When to Migrate:** When horizontally scaling across multiple container instances (since SQLite cannot accept concurrent network writes across hosts) or when write concurrency exceeds 200 writes/sec.
  - **Migration Requirements:**
    1. Update SQLAlchemy database URL from `sqlite+aiosqlite:///data/saferoute.db` to `postgresql+asyncpg://user:pass@host:5432/saferoute`.
    2. Replace SQLite-specific `PRAGMA` statements with standard PostgreSQL connection pooling (`pool_size=20`, `max_overflow=10`).
    3. Run Alembic migrations to generate PostgreSQL schemas with matching foreign keys and indexes.

### 2.6 Streaming Backpressure & Cancellation Handling
- **Mechanism:** Implemented via Starlette's `StreamingResponse` using an asynchronous generator (`async for chunk in provider.stream(...)`).
- **Client Disconnection Detection:** The gateway continuously monitors client socket liveness via `request.is_disconnected()`.
- **Cancellation Propagation:** When a client aborts an HTTP stream (e.g. closing the browser tab or terminating an HTTP client), the generator catches `asyncio.CancelledError`.
- **Upstream Connection Termination:** The gateway immediately closes the upstream HTTP connection to Ollama/upstream provider, terminating downstream GPU compute and releasing local worker threads.
- **Usage Accounting on Interruption:** Tokens emitted prior to disconnection are recorded in SQLite with status `cancelled_by_client` and exact token counts preserved.

### 2.7 Heuristic Guardrails: Scope & Limitations
- **Defense-in-Depth, Not a Formal Proof:** SafeRoute's guardrails are heuristic filters (regex pattern matchers, keyword blocklists, and lightweight classifier probes).
- **Intended Purpose:** Catch common prompt injection attempts (e.g., "ignore all previous instructions"), accidental PII leakage (SSNs, credit card numbers, email patterns), and prohibited system keywords before requests reach the LLM.
- **Limitations:** Heuristic guardrails cannot formally guarantee 100% prevention of sophisticated multi-turn semantic jailbreaks or zero-day adversarial token sequences. True enterprise safety requires layered defenses (gateway guardrails + model-level safety fine-tuning + runtime sandboxing).

---

## 3. Technology Stack Reference

| Tier | Component | Selection Rationale |
|---|---|---|
| **API Framework** | FastAPI (Python 3.11+) | Async native, Pydantic v2 validation, OpenAPI autodoc, Starlette SSE streaming |
| **Data Persistence** | SQLite 3 (WAL Mode) | Zero-dependency, file-based embedded storage, ACID-compliant audit logging |
| **ORM / Migration** | SQLAlchemy 2.0 (Async) | Clean query abstraction, async session management, seamless PostgreSQL portability |
| **Cache & Limiting** | Redis 7+ | In-memory atomic data structures, sub-millisecond exact caching, Lua script execution |
| **Inference Engine** | Local Ollama | Offline, free local LLM execution (`llama3.2:1b`, Q8_0 GGUF), OpenAI-compatible API |
| **Observability** | Prometheus Exporter | Standard exposition on `/metrics`, histogram latency tracking, gauge stream counts |
| **Frontend UI** | React 19 + TypeScript + Vite | Route-level lazy loading (318 kB bundle), responsive dark mode design system |
| **Containerization** | Docker & Compose | Multi-stage distroless-like builds, healthcheck probes, non-root user execution |
