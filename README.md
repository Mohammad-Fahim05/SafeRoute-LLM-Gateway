# SafeRoute LLM Gateway

[![CI](https://github.com/Mohammad-Fahim05/SafeRoute-LLM-Gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/Mohammad-Fahim05/SafeRoute-LLM-Gateway/actions/workflows/ci.yml)
[![Release](https://img.shields.io/badge/Release-v1.0.0-green.svg)](https://github.com/Mohammad-Fahim05/SafeRoute-LLM-Gateway/releases/tag/v1.0.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

SafeRoute is a lightweight, reliable, and observable LLM Gateway built with Python and FastAPI. It sits between client applications and AI model providers, standardizing chat completions, enforcing security and authentication, managing timeouts, and providing unified error handling, structured logging, and observability.

---

## Table of Contents
- [What is an LLM Gateway?](#what-is-an-llm-gateway)
- [The Problem SafeRoute Solves](#the-problem-saferoute-solves)
- [Gateway Keys vs. Upstream Provider Keys](#gateway-keys-vs-upstream-provider-keys)
- [Architecture Diagram](#architecture-diagram)
- [Phase Implementation Status](#phase-implementation-status)
- [Hybrid RAG & Retrieval Engine (Decoupled Extension)](#hybrid-rag--retrieval-engine)
- [Project Structure](#project-structure)
- [Setup and Installation](#setup-and-installation)
- [Client API-Key Authentication (Phase 2)](#client-api-key-authentication-phase-2)
  - [Security Design (HMAC-SHA256)](#security-design-hmac-sha256)
  - [Generating a New Client API Key](#generating-a-new-client-api-key)
  - [Configuring and Revoking Keys](#configuring-and-revoking-keys)
- [Ollama Provider Integration (Phase 2)](#ollama-provider-integration-phase-2)
  - [Installing and Running Local Ollama](#installing-and-running-local-ollama)
  - [Pulling a Suitable Model](#pulling-a-suitable-model)
  - [Configuring the Gateway for Ollama vs. Mock](#configuring-the-gateway-for-ollama-vs-mock)
- [Persistent SQLite Database & Usage Tracking (Phase 3)](#persistent-sqlite-database--usage-tracking-phase-3)
  - [Beginner's Guide to the Database Schema](#beginners-guide-to-the-database-schema)
  - [Database File Location & Configuration](#database-file-location--configuration)
  - [Database Initialization, Backup, and Restore](#database-initialization-backup-and-restore)
  - [Database Failure Behavior (Strict vs. Resilient)](#database-failure-behavior-strict-vs-resilient)
- [Token Provenance & Versioned Cost Estimation (Phase 3)](#token-provenance--versioned-cost-estimation-phase-3)
  - [Token Usage Provenance](#token-usage-provenance)
  - [Versioned Model Pricing & Decimal Arithmetic](#versioned-model-pricing--decimal-arithmetic)
  - [Local Ollama & Mock Handling](#local-ollama--mock-handling)
- [Usage Summary & CSV Export (Phase 3)](#usage-summary--csv-export-phase-3)
  - [Usage Summary Endpoint (`GET /v1/usage/summary`)](#usage-summary-endpoint-get-v1usagesummary)
  - [CSV Export Endpoint (`GET /v1/usage/export`)](#csv-export-endpoint-get-v1usageexport)
  - [CLI Export Utility (`scripts/export_usage.py`)](#cli-export-utility-scriptsexport_usagepy)
  - [Data Isolation & Privacy Protection](#data-isolation--privacy-protection)
- [Redis Integration & Exact-Match Response Caching (Phase 4)](#redis-integration--exact-match-response-caching-phase-4)
  - [What Exact-Match Caching Does and Does Not Do](#what-exact-match-caching-does-and-does-not-do)
  - [Local Redis Setup Instructions (Windows & Docker)](#local-redis-setup-instructions-windows--docker)
  - [Configuration Variables and Defaults](#configuration-variables-and-defaults)
  - [Cache-Key Design & Strict Client Isolation](#cache-key-design--strict-client-isolation)
  - [Request Processing Order & Cache Eligibility](#request-processing-order--cache-eligibility)
  - [Cache-Hit vs. Cache-Miss Behavior](#cache-hit-vs-cache-miss-behavior)
  - [TTL & Invalidation Mechanisms](#ttl--invalidation-mechanisms)
  - [Redis Outage & Fail-Open Behavior](#redis-outage--fail-open-behavior)
  - [SQLite Integration & Usage Accounting on Cache Hits](#sqlite-integration--usage-accounting-on-cache-hits)
  - [Security and Privacy Implications](#security-and-privacy-implications)
- [Redis-Backed Client Rate Limiting (Phase 5)](#redis-backed-client-rate-limiting-phase-5)
  - [What Rate Limiting Does & Why It Is Needed](#what-rate-limiting-does--why-it-is-needed)
  - [Atomic Fixed-Window Algorithm & Lua Script](#atomic-fixed-window-algorithm--lua-script)
  - [Algorithm Trade-Offs & Limitations](#algorithm-trade-offs--limitations)
  - [Configuration Variables and Defaults](#configuration-variables-and-defaults-phase-5)
  - [Client Identity & Cryptographic Isolation](#client-identity--cryptographic-isolation)
  - [HTTP 429 Too Many Requests & Headers](#http-429-too-many-requests--headers)
  - [Redis Outage Behavior (Fail-Closed vs. Fail-Open)](#redis-outage-behavior-fail-closed-vs-fail-open)
  - [Interaction with Cache Hits, Provider Calls, and Safety Checks](#interaction-with-cache-hits-provider-calls-and-safety-checks)
  - [SQLite Request & Usage Accounting](#sqlite-request--usage-accounting)
- [Configurable Input and Output Guardrails (Phase 6)](#configurable-input-and-output-guardrails-phase-6)
  - [What Guardrails Do & Why They Are Needed](#what-guardrails-do--why-they-are-needed)
  - [Deterministic Rule Matching vs. Semantic AI Safety](#deterministic-rule-matching-vs-semantic-ai-safety)
  - [Configuration Variables & Safe Defaults](#configuration-variables--safe-defaults-phase-6)
  - [Rule Definition Format & Match Types](#rule-definition-format--match-types)
  - [Startup Validation & ReDoS Protection](#startup-validation--redos-protection)
  - [Input Inspection & Rate Limit Interaction](#input-inspection--rate-limit-interaction)
  - [Output Inspection, Stale Cache Invalidation & Usage Accounting](#output-inspection-stale-cache-invalidation--usage-accounting)
  - [Privacy & Structured Audit Logging](#privacy--structured-audit-logging)
- [Reproducible Evaluation and Benchmarking Framework (Phase 7)](#reproducible-evaluation-and-benchmarking-framework-phase-7)
  - [What the Evaluation Framework Measures](#what-the-evaluation-framework-measures)
  - [Versioned Evaluation Dataset Format](#versioned-evaluation-dataset-format)
  - [Running a Quick Local Evaluation](#running-a-quick-local-evaluation)
  - [Running a Full Evaluation with Performance Benchmarks](#running-a-full-evaluation-with-performance-benchmarks)
  - [Interpreting Evaluation & Benchmark Metrics](#interpreting-evaluation--benchmark-metrics)
  - [Mock Doubles vs. Live External Services](#mock-doubles-vs-live-external-services)
  - [Report Generation & Safe Artifact Storage](#report-generation--safe-artifact-storage)
  - [Statistical Caution & Limitations](#statistical-caution--limitations)
- [Running the Gateway](#running-the-gateway)
- [API Reference & Examples](#api-reference--examples)
  - [Liveness Check (`GET /health`)](#liveness-check-get-health)
  - [Readiness Check (`GET /ready`)](#readiness-check-get-ready)
  - [Authenticated Chat Completion (`POST /v1/chat/completions`)](#authenticated-chat-completion-post-v1chatcompletions)
  - [Streaming Chat Completions (Phase 9.2)](#streaming-chat-completions-phase-92)
  - [Unified Tool / Function Calling (Phase 9.3)](#unified-tool--function-calling-phase-93)
  - [Usage Statistics (`GET /v1/usage/summary`)](#usage-statistics-get-v1usagesummary)
  - [Usage Export (`GET /v1/usage/export`)](#usage-export-get-v1usageexport)
  - [Authentication & Validation Error Responses](#authentication--validation-error-responses)
  - [Guardrail Rejection Error Responses](#guardrail-rejection-error-responses)
- [Semantic Caching & Performance Benchmark (Phase 10)](#semantic-caching--performance-benchmark-phase-10)
  - [Exact vs. Semantic Cache Architecture](#exact-vs-semantic-cache-architecture)
  - [Safety Gates & Adversarial Protections](#safety-gates--adversarial-protections)
  - [Local-Only Configuration & Setup](#local-only-configuration--setup)
  - [Benchmark Methodology & Latency Results](#benchmark-methodology--latency-results)
  - [Reproduction Commands](#reproduction-commands)
- [Docker Compose Deployment Foundation (Phase 11A)](#docker-compose-deployment-foundation-phase-11a)
  - [Prerequisites and Architecture](#prerequisites-and-architecture)
  - [Required Environment Variables & Configuration](#required-environment-variables--configuration)
  - [Windows Development vs. Docker Compose Deployment](#windows-development-vs-docker-compose-deployment)
  - [Docker Compose Startup, Logs, and Shutdown](#docker-compose-startup-logs-and-shutdown)
  - [Host Ollama Connectivity (`host.docker.internal`)](#host-ollama-connectivity-hostdockerinternal)
  - [Database Persistence, WAL Files, and Backup Considerations](#database-persistence-wal-files-and-backup-considerations)
  - [Health Probes & Readiness Separation (`/health` vs. `/ready`)](#health-probes--readiness-separation-health-vs-ready)
  - [Security Architecture & Container Hardening](#security-architecture--container-hardening)
  - [Troubleshooting & Diagnostics](#troubleshooting--diagnostics)
- [Prometheus Metrics & Observability (Phase 11B)](#prometheus-metrics--observability-phase-11b)
  - [Overview & Metric Architecture](#overview--metric-architecture)
  - [Exposed Metrics Catalog](#exposed-metrics-catalog)
  - [Configuration & Security Options](#configuration--security-options)
  - [Sample Prometheus Exposition Output](#sample-prometheus-exposition-output)
  - [Zero Double-Counting & Provenance Handling](#zero-double-counting--provenance-handling)
  - [Prometheus & Docker Compose Scraping Configuration](#prometheus--docker-compose-scraping-configuration)
- [Streaming Cache Replay (Phase 11C)](#streaming-cache-replay-phase-11c)
  - [Architecture & Compatibility Guarantees](#architecture--compatibility-guarantees)
  - [Safe Cache Eligibility Rules](#safe-cache-eligibility-rules)
  - [OpenAI SSE Replay Protocol](#openai-sse-replay-protocol)
  - [Zero Double-Counting & Metrics Accuracy](#zero-double-counting--metrics-accuracy)
  - [Failure, Disconnect & Adversarial Protections](#failure-disconnect--adversarial-protections)
  - [Configuration & Live Validation](#configuration--live-validation)
- [Operational Hardening & Production Readiness (Phase 12)](#operational-hardening--production-readiness-phase-12)
  - [Configuration Validation & Startup Safety (Phase 12A)](#configuration-validation--startup-safety-phase-12a)
  - [Failure Recovery, Readiness & SQLite Hardening (Phase 12B)](#failure-recovery-readiness--sqlite-hardening-phase-12b)
  - [CORS & Defensive HTTP Security Headers (Phase 12C)](#cors--defensive-http-security-headers-phase-12c)
  - [Controlled Load Testing & Benchmarking (Phase 12D)](#controlled-load-testing--benchmarking-phase-12d)
- [Running Tests](#running-tests)
- [Portfolio Release Summary & Architecture](#portfolio-release-summary--architecture)
- [Known Limitations & Roadmap](#known-limitations--roadmap)

---

## What is an LLM Gateway?

An **LLM Gateway** is a specialized reverse proxy and API orchestration layer for Large Language Models. Instead of every client application directly calling varied, disparate model providers (such as local Ollama instances, OpenAI, or Anthropic), clients send standard requests to SafeRoute.

The gateway validates requests, authenticates callers, routes to the appropriate backend provider, captures actual token metrics, logs structured audit events without leaking prompt data, records durable usage in SQLite, and isolates the application from upstream outages.

```
+--------------------+            +------------------------+            +----------------------+
| Client Application |  Bearer    | SafeRoute LLM Gateway  |   Local    | Upstream LLM Backend |
| (Your App / Agent) | ---------> | (Auth, Limits, Proxy)  | ---------> | (Mock or Ollama)     |
|                    | <--------- |   + SQLite Records     | <--------- |                      |
+--------------------+  JSON      +------------------------+   HTTP     +----------------------+
```

---

## The Problem SafeRoute Solves

When applications interact directly with model backends, critical engineering problems arise:
1. **Uncontrolled API Access**: Anyone with network access can query costly model backends without authentication or rate controls.
2. **Key Sprawl & Security Risks**: Embedding upstream cloud API keys in frontends or multiple microservices risks credential leakage.
3. **Disparate APIs & Observability Gaps**: Tracking latency, errors, and token usage across different services is nearly impossible without a unified gateway.
4. **Inconsistent Error Behavior**: Raw provider outages or timeouts cause uncaught exceptions or leak stack traces to clients.
5. **Opaque Usage & Costs**: Without durable database records and token provenance, engineering teams cannot audit model consumption or bill clients accurately.

SafeRoute solves this by centralizing security, standardized request/response formatting, robust error normalization, and persistent cost estimation.

---

## Gateway Keys vs. Upstream Provider Keys

Understanding the distinction between these two keys is essential:

| Feature | Gateway Client API Key (`gw_test_...`) | Upstream Provider Key (`sk-...`, etc.) |
| :--- | :--- | :--- |
| **Purpose** | Authenticates your client apps to the SafeRoute Gateway. | Authenticates SafeRoute to upstream AI cloud providers (future phases). |
| **Who Has It?** | Your internal microservices, developers, or frontend apps. | Kept strictly private inside SafeRoute's server environment. |
| **Format** | `gw_test_<random_urlsafe_bytes>` | Provider-specific (e.g. OpenAI `sk-...`, Claude `sk-ant-...`). |
| **Storage in Gateway**| **Never stored in plaintext**. Stored as a keyed HMAC-SHA256 verifier in config and synced as audit records in SQLite. | Stored encrypted or in environment variables on the gateway server. |
| **Local Ollama** | Required to access SafeRoute. | Not applicable (local Ollama requires no upstream API key). |

> [!IMPORTANT]
> SafeRoute **never** accepts upstream provider API keys as gateway client credentials. Clients must present a valid gateway key.

---

## Architecture Diagram

```mermaid
flowchart TD
    Client([Client Application]) -->|1. HTTP Request with Bearer Token| Middleware[RequestTrackingMiddleware]

    subgraph Gateway Core [SafeRoute LLM Gateway]
        Middleware -->|2. Extract Request ID & Check Payload Size| AuthCheck{Verify API Key?}

        AuthCheck -- Public Health/Ready --> RouteDirect[Health / Ready Handlers]
        AuthCheck -- Missing / Invalid Key --> 401[Return HTTP 401 Unauthorized]
        AuthCheck -- Valid Key --> Router[FastAPI Chat Router]

        Router -->|3. Validate Model & Request Limits| Allowlist{In Allowed Models & Limits?}
        Allowlist -- No --> 400Model[Return 400 / 422 Error]
        Allowlist -- Yes --> RateCheck{Rate Limit Check - Redis}

        RateCheck -- Limit Exceeded --> 429Rate[Return HTTP 429 Too Many Requests]
        RateCheck -- Redis Down fail_closed --> 503Rate[Return HTTP 503 Service Unavailable]
        RateCheck -- Allowed / fail_open --> InputGuard{4. Input Guardrails Check}

        InputGuard -- Blocked Rule/Size --> 400Guard[Return HTTP 400 input_guardrail_blocked]
        InputGuard -- Passed --> CacheCheck{5. Cache Enabled & Eligible?}

        CacheCheck -- Yes --> CacheLookup[Redis Exact Cache Lookup]
        CacheLookup -- Hit --> CachedGuard{Output Guardrail on Cache?}
        CachedGuard -- Blocked --> InvalidateCache[Delete Stale Cache Entry & Return 502]
        CachedGuard -- Passed --> CacheReturn[Reconstruct Response & New Request ID]
        CacheLookup -- Miss / Error --> ProviderRegistry[Provider Registry]
        CacheCheck -- No / Disabled --> ProviderRegistry

        ProviderRegistry -->|ACTIVE_PROVIDER = 'mock'| MockEngine[MockProvider In-Memory]
        ProviderRegistry -->|ACTIVE_PROVIDER = 'ollama'| OllamaEngine[OllamaProvider AsyncClient]

        MockEngine --> ProviderOutGuard{6. Output Guardrails Check}
        OllamaEngine --> ProviderOutGuard
        ProviderOutGuard -- Blocked --> 502Guard[Return 502 output_guardrail_blocked & Record Usage]
        ProviderOutGuard -- Passed --> ProviderAllowed[Cache Response & Return 200]

        Router --> PricingEngine[Versioned Pricing & Calculator]
        Router --> DBService[Database Service]
    end

    subgraph Redis Backend [Redis Service]
        RateCheck <-->|Atomic Lua INCR+EXPIRE| RedisRate[(Redis: 6379 Rate Limiting)]
        CacheLookup <--> RedisCache[(Redis: 6379 Cache)]
        ProviderAllowed -.->|On Miss & Success: Write Cache| RedisCache
        InvalidateCache -.->|Delete Stale Entry| RedisCache
    end

    subgraph Upstream [Local AI Service]
        OllamaEngine -->|POST /api/chat| OllamaService[Local Ollama Server: 11434]
        OllamaService -->|Raw Response + Tokens| OllamaEngine
    end

    subgraph Persistence [SQLite Storage]
        DBService --> SQLite[(SQLite DB: saferoute.db)]
    end

    ProviderAllowed -->|Persist Request & Usage| DBService
    502Guard -->|Persist Provider Tokens & Block Status| DBService
    400Guard -->|Persist Block Status (0 Provider Usage)| DBService
    ProviderAllowed -->|Headers: X-Request-ID, X-RateLimit-*, X-Cache| Client
    CacheReturn -->|Persist Cache Hit (0 Provider Cost)| DBService
    CacheReturn -->|Headers: X-Request-ID, X-RateLimit-*, X-Cache: HIT| Client
```

---

## Phase Implementation Status

#### Implemented in Phases 1 through 9.3:
- **Endpoints**: `GET /health`, `GET /ready`, `POST /v1/chat/completions`, `GET /v1/usage/summary`, and `GET /v1/usage/export`.
- **Client Authentication (Phase 2)**: Bearer API key authentication via keyed HMAC-SHA256 (`gw_test_...`).
- **Key Management Utility (Phase 2)**: CLI script (`scripts/manage_keys.py`) to generate keys, show them once, and output safe configuration hashes.
- **Key Revocation (Phase 2)**: Configuration-backed revocation (`enabled: false` or key removal).
- **Ollama Provider Adapter (Phase 2)**: Asynchronous HTTP adapter (`httpx.AsyncClient`) calling local Ollama (`/api/chat`), normalizing responses, and capturing real provider-reported token usage.
- **Provider Switching (Phase 2)**: Toggle `ACTIVE_PROVIDER=ollama` or `mock`.
- **Deterministic MockProvider**: Cost-free, in-memory testing engine with error and timeout simulation modes.
- **Request ID Tracking**: Request IDs generated via UUID or validated from incoming `X-Request-ID` headers; tracked via `contextvars`. Fresh ID per incoming request guaranteed on cache hits and rate limit rejections.
- **Structured JSON Logging**: Safe JSON logging that avoids logging prompt content, personal data, or secrets.
- **Standardized Error Responses**: Uniform error JSON format with specific HTTP status codes (400, 401, 413, 422, 429, 502, 503, 504, 500).
- **Persistent SQLite Database (Phase 3)**: SQLAlchemy 2.0 relational storage for requests, token usage, client registry, and key audit logs with WAL mode and foreign key enforcement.
- **Token Usage Provenance (Phase 3)**: Explicit usage states (`provider_reported`, `mock_estimated`, `unavailable`, `cache_hit`) with missing tokens kept as `null` instead of misleading zero.
- **Versioned Pricing & Cost Estimation (Phase 3)**: Auditable JSON pricing catalog (`2026-10-v3`) with high-precision Python `Decimal` arithmetic.
- **Usage Reporting & CSV Export (Phase 3)**: Client-isolated usage summaries (`GET /v1/usage/summary`), web CSV exports (`GET /v1/usage/export`), and CLI export script (`scripts/export_usage.py`).
- **Redis Integration & Exact-Match Response Caching (Phase 4)**: Asynchronous Redis client (`redis.asyncio`), deterministic SHA-256 cache key canonicalization, strict client isolation, finite TTL expiration, `X-Cache` response headers (`HIT`, `MISS`, `DISABLED`, `BYPASS`, `ERROR`), and fail-open outage resilience.
- **Zero-Cost Cache Hits (Phase 4)**: Cache hits are accurately recorded in SQLite with `cache_status='hit'`, zero provider latency, and zero incremental cloud token charges.
- **Redis-Backed Client Rate Limiting (Phase 5)**: Distributed, atomic Lua-script-backed fixed window limiter running on Redis. Enforces quotas per authenticated client identity, protects against race conditions across multiple gateway workers, injects standard rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`), and durably audits HTTP 429 rejections in SQLite without invoking downstream providers or generating fake token usage.
- **Configurable Outage Policy (Phase 5)**: Secure `fail_closed` default returning HTTP 503 (`rate_limiter_unavailable`) or operator-selected `fail_open` mode when Redis is degraded.
- **Configurable Input and Output Guardrails (Phase 6)**: Controlled deterministic rule framework inspecting incoming message turns and upstream completions. Supports `regex`, `contains`, and `keyword` word-boundary rules with case-sensitivity controls.
- **ReDoS Processing Bounds (Phase 6)**: Guardrail character length bounds (`GUARDRAILS_MAX_TEXT_LENGTH`) prevent catastrophic regex backtracking on pathological client inputs.
- **Stale Cache Invalidation (Phase 6)**: Cached completions are evaluated against current output guardrail policies prior to return; violating entries are evicted from Redis and return HTTP 502.
- **Truthful Token Accounting for Blocked Output (Phase 6)**: Provider token counts and execution latencies are preserved in SQLite audit logs when outputs are blocked, avoiding accounting discrepancies while withholding prohibited text from clients.
- **Reproducible Evaluation Framework (Phase 7)**: Versioned deterministic evaluation dataset (`datasets/evaluation/default_suite.json`) testing comprehensive scenarios including authentication, validation, caching, rate limiting, guardrails, provider timeouts, provider errors, and Redis outages.
- **Automated Performance Micro-Benchmarking (Phase 7)**: Monotonic timer harness measuring mean, p50, p95, and p99 latencies, cache hit ratios, and throughput (rps) across cold vs warm caching, cache disabled baseline, guardrail evaluation overhead, and provider error normalization.
- **Dual-Format Evaluation Reports (Phase 7)**: Machine-readable JSON reports and human-readable Markdown summaries saved to `data/evaluation_results/` with zero credential or prompt leakage.
- **CLI Runner Utility (Phase 7)**: `scripts/run_evaluation.py` supporting `--mode quick`, `--mode full`, `--benchmark`, `--benchmark-iterations`, and `--live`.
- **Focused Local Scope & Architecture Simplification (Phase 8)**: Streamlined architecture focusing exclusively on local Ollama inference and Mock testing. Unused external cloud providers (Anthropic Claude and Google Gemini) have been completely removed to reduce dependencies, attack surface, and operational complexity.
- **Multi-Provider Failover (Phase 9.1 & 9.1.1)**: Configurable, observable automatic failover across models on eligible 429/5xx/timeout errors before response headers are sent, with failover observability headers (`X-Serving-Provider`, `X-Serving-Model`, `X-Failover-Occurred`, `X-Failover-Attempts`).
- **Streaming Responses (Phase 9.2)**: Server-Sent Events (SSE, `Content-Type: text/event-stream`) streaming completions across Mock and Ollama providers with pre-stream failover, incremental output guardrails, client disconnect cancellation, cache replay, and sanitized mid-stream error events.
- **Unified Tool / Function-Calling Normalization (Phase 9.3)**: Standardized OpenAI-compatible tool definitions (`tools`, `tool_choice`) normalized across Ollama and Mock providers. Preserves strict non-execution boundary (gateway never executes model code), enforces schema validation limits, manages tool-result associations (`role: "tool"`), streams tool-call deltas (`delta.tool_calls`), isolates cache keys via SHA-256 tool canonicalization, enforces tool capability during pre-stream failover, and protects argument privacy.
- **Semantic Caching & Invariant Protection (Phase 9.4 / 10)**: Two-tiered cache hierarchy with optional Level 2 semantic cache (`SemanticResponseCache`) alongside Level 1 exact Redis cache. Pluggable local offline embedding architecture (`all-MiniLM-L6-v2`, 384-dim) and deterministic mock provider. Enforces strict tenant isolation, system prompt equality, history digest consistency, generation parameter tolerance, and adversarial invariant checks (negation polarity and numeric entity matching) to achieve 0% false-positive reuse. Full zero-cost provenance accounting ($0.00 provider cost, `semantic_hit`), observability headers (`X-Cache-Layer: semantic`, `X-Cache-Similarity: 0.xxxx`), and comprehensive benchmarking suite.
- **Docker Compose Deployment Foundation (Phase 11A)**: Production-grade multi-stage `Dockerfile` with non-root security (`saferoute` user, UID/GID 10001), container health probes (`/health`, `/ready`), `docker-compose.yml` orchestrating `gateway` and `redis:7-alpine`, named persistent Docker volumes (`saferoute-sqlite-data` and `saferoute-redis-data`) guaranteeing SQLite WAL persistence across container lifecycles, host Ollama routing (`host.docker.internal:11434`), `.dockerignore` for zero credential leakage, and 100% offline regression passing.
- **Prometheus Metrics & Observability (Phase 11B)**: Standard Prometheus text exposition (`GET /metrics`) instrumented with strictly bounded labels (route, status, provider, model, source), latency histograms for gateway and upstream providers, timeout/error counters, exact and semantic cache event tracking, token counters with source provenance, active stream gauge, rate limit rejections, and guardrail blocks. Configurable scraper authentication (`METRICS_REQUIRE_AUTH`, `METRICS_AUTH_TOKEN`) and fail-safe error isolation.
- **Streaming Cache Replay (Phase 11C)**: Deterministic, chunk-by-chunk replay of cached streaming responses from Redis with simulated token delays, SSE frame validation, and exact guardrail enforcement.
- **Comprehensive Automated Test Suite**: 406 passed and 3 skipped unit and integration tests covering all gateway security, database, exact & semantic cache, limiter, guardrail, provider, failover, streaming, metrics, and management API lifecycles.
- **Frontend Management Console (Phase 13)**: Complete, production-grade single-page application built with React 19, TypeScript, Vite, Tailwind CSS, Lucide icons, Recharts, and TanStack Query. Features a strictly colorful `#11152E` indigo/violet/teal palette (no plain black or white), collapsible navigation shell, live status indicators, session authentication modal, and 11 functional modules:
  1. **Overview Dashboard**: Aggregate KPIs, latency percentiles (P50/P95/P99), cache hit rate, token volumes, interactive area chart, and recent activity table.
  2. **Request Explorer**: Filterable, searchable, and paginated request browser with slide-out request detail drawer, failover attempt timeline, token accounting, and zero-payload privacy guarantee.
  3. **LLM Playground**: Interactive testing playground connected to the real gateway (`/v1/chat/completions`), supporting real SSE streaming token generation, stop generation, temperature and token controls, request duration, and copy response.
  4. **Providers & Routing**: Local Ollama runtime probe (`/api/tags`), installed model tags, MockProvider test double status, pruned cloud provider clarification, and capability matrix.
  5. **Cache & Redis Observability**: Telemetry distinguishing Redis connection ping, exact SHA-256 caching, semantic similarity caching, and zero-drop fail-open resilience policies.
  6. **Usage & Token Analytics**: Token consumption trends, model allocation charts, and truthful cost accounting highlighting $0.00 incurred cloud costs vs simulated avoided API expenses, with CSV export.
  7. **SQLite Database Explorer**: Safe read-only inspection of active schema, storage file size, WAL journal mode, and paginated record browser for whitelisted audit tables without write/alter risks.
  8. **Errors & Gateway Reliability**: Error taxonomy, 401 client guards, 429 rate throttles, circuit breakers, and fault tolerance architecture.
  9. **System Health & Prometheus**: Component health probes (Gateway, SQLite, Redis, Ollama) and a live `/metrics` Prometheus stream explorer with real-time key filtering.
  10. **Security & Guardrails**: Documentation and audit of timing-safe HMAC authentication (`hmac.compare_digest`), automated PII redaction filters, prompt injection heuristics, and client data isolation.
  11. **Configuration & Documentation**: Sanitized gateway runtime settings viewer with masked secrets and quick startup runbooks.

### Scheduled for Future Phases:
- **OpenTelemetry Tracing**: Distributed context propagation and spans.

- **Streaming Cache Replay**: Chunked SSE replay from Redis cache.
- **Semantic AI Safety Classifiers**: External ML models or multi-modal classifiers.
- **Kubernetes / Production Helm Charts**: Cloud-native deployment manifests and dashboards.

---

## Project Structure

```text
d:/SafeRoute LLM Gateway/
├── .env.example              # Example environment configuration with Phase 2-6 settings
├── .gitignore                # Git ignore patterns (excluding data/ and evaluation_results/)
├── pyproject.toml            # Project packaging and dependencies
├── README.md                 # Complete documentation
├── datasets/
│   └── evaluation/
│       └── default_suite.json# Versioned deterministic evaluation dataset
├── scripts/
│   ├── export_usage.py       # CLI tool to export usage data as CSV
│   ├── manage_keys.py        # CLI tool to generate and manage gateway API keys
│   └── run_evaluation.py     # CLI runner for reproducible evaluation & benchmarks
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI entry point, tracking middleware, lifespan
│   ├── config.py             # Settings using pydantic-settings with validators
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py         # Endpoints with verify_api_key & exact caching
│   │   └── schemas.py        # Strict Pydantic v2 schemas (extra="forbid")
│   ├── cache/
│   │   ├── __init__.py       # Cache module exports
│   │   └── redis_cache.py    # Redis async client, canonical keys, TTL, and resilience
│   ├── core/
│   │   ├── __init__.py
│   │   ├── auth.py           # HMAC-SHA256 verification & FastAPI auth dependency
│   │   ├── errors.py         # Standardized error normalization & handlers
│   │   ├── logging.py        # Safe structured JSON logger (redacting secrets/prompts)
│   │   └── request_context.py# Request ID and client ID contextvars manager
│   ├── db/
│   │   ├── __init__.py       # Database initialization and exports
│   │   ├── models.py         # SQLAlchemy 2.0 models (Client, RequestRecord, UsageRecord)
│   │   ├── service.py        # DatabaseService for persistence and aggregation
│   │   └── session.py        # Engine and session lifecycle management
│   ├── evaluation/
│   │   ├── __init__.py       # Evaluation module exports
│   │   ├── benchmarker.py    # PerformanceBenchmarker measuring latency and throughput
│   │   ├── loader.py         # Dataset loading and Pydantic validation
│   │   ├── models.py         # Data models for cases, datasets, results, and benchmarks
│   │   ├── reporter.py       # Report serializers for JSON and Markdown
│   │   └── runner.py         # Deterministic EvaluationRunner executing cases in sandboxes
│   ├── guardrails/
│   │   ├── __init__.py       # Guardrail dependency injection and module exports
│   │   ├── engine.py         # Deterministic input & output inspection engine
│   │   └── models.py         # GuardrailRule and GuardrailResult dataclasses
│   ├── pricing/
│   │   ├── __init__.py
│   │   ├── calculator.py     # Versioned pricing engine and cost calculations
│   │   └── models_pricing.json # Machine-readable pricing catalog
│   ├── providers/
│   │   ├── __init__.py       # Provider registry & lookup
│   │   ├── base.py           # Abstract BaseLLMProvider interface
│   │   ├── mock.py           # Deterministic in-memory mock provider
│   │   └── ollama.py         # Local Ollama asynchronous HTTP provider adapter
│   └── ratelimit/
│       ├── __init__.py       # Rate limiter dependency injection & exports
│       ├── limiter.py        # Atomic Lua-script-backed fixed-window rate limiter
│       └── models.py         # RateLimitResult data model
└── tests/
    ├── __init__.py
    ├── conftest.py           # Test settings overrides and authentication fixtures
    ├── unit/
    │   ├── test_auth.py      # HMAC verification and token parsing unit tests
    │   ├── test_cache.py     # Cache key canonicalization and fail-open tests
    │   ├── test_config.py    # Config unit tests
    │   ├── test_database.py  # SQLite schema, foreign key, and persistence unit tests
    │   ├── test_evaluation.py# Dataset validation, quantiles, and redaction unit tests
    │   ├── test_guardrails.py# Guardrail rules, regex compilation, and bound unit tests
    │   ├── test_mock_provider.py # Mock provider & offline isolation tests
    │   ├── test_ollama_provider.py # Ollama adapter tests using httpx.MockTransport
    │   ├── test_pricing.py   # Versioned pricing and Decimal math unit tests
    │   ├── test_rate_limiter.py # Atomic Lua rate limiter unit tests
    │   └── test_schemas.py   # Pydantic validation unit tests
    └── integration/
        ├── test_auth_integration.py # 401 missing, malformed, invalid, revoked tests
        ├── test_caching.py   # Exact-match caching integration tests
        ├── test_chat_completions.py # Chat completion integration tests
        ├── test_errors.py    # Timeouts, 502, 504, 400, 422, 500 error tests
        ├── test_evaluation.py# Evaluation runner, benchmarks, and CLI integration tests
        ├── test_guardrails.py# Input/output guardrail enforcement and audit tests
        ├── test_health.py    # Public /health and /ready integration tests
        ├── test_ollama_integration.py # Ollama provider integration & routing tests
        ├── test_rate_limiting.py # Rate limiting integration & HTTP 429 tests
        └── test_usage_and_costs.py # Database persistence, summary, and CSV export tests
```

---

## Setup and Installation

### Prerequisites
- Python **3.10+** (tested on Python 3.13)
- `pip`

### 1. Clone or Open the Workspace
```bash
cd "d:/SafeRoute LLM Gateway"
```

### 2. (Optional) Create a Virtual Environment
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install fastapi uvicorn pydantic pydantic-settings httpx pytest sqlalchemy redis
```

### 4. Running the Backend Gateway (Windows PowerShell)
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
The gateway will start on `http://localhost:8000`.

### 5. Running the Frontend Management Console
The management console is located in the `frontend/` directory.

```powershell
# Navigate to the frontend directory
cd frontend

# Install Node.js dependencies
npm install

# Start the Vite development server (proxies /api and /v1 to http://localhost:8000)
npm run dev
```
Open your browser at `http://localhost:5173` to access the colorful SafeRoute Management Console.

### 6. Production Frontend Build
```powershell
cd frontend
npm run build
```
Generates an optimized, type-checked, minified bundle in `frontend/dist/`.

---

## Client API-Key Authentication (Phase 2)


### Security Design (HMAC-SHA256)

1. **Random High-Entropy Keys**: Keys are generated using Python's `secrets` module with prefix `gw_test_` (e.g. `gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8`).
2. **Never Stored in Plaintext**: The server never saves the plaintext key anywhere.
3. **Keyed HMAC-SHA256 Verifiers**: SafeRoute computes a cryptographic hash of the key combined with a server-side `AUTH_SECRET`:
   $$\text{Verifier} = \text{HMAC-SHA256}(\text{AUTH\_SECRET}, \text{Plaintext Key})$$
4. **Timing-Attack Resistance**: Verification uses `hmac.compare_digest` for constant-time comparison, preventing side-channel attacks.
5. **Fail-Closed Architecture**: If `AUTH_SECRET` is missing or invalid, all authenticated requests are rejected immediately.

---

### Generating a New Client API Key

Use the included key management utility:

```bash
python scripts/manage_keys.py create --client-id mobile_app --secret "your_strong_secret_at_least_16_chars"
```

Output:
```text
======================================================================
SafeRoute Gateway Client API Key Generated
======================================================================

Client ID: mobile_app

Plaintext API Key:
  gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8

  [!] CAUTION: This key is displayed only ONCE.
      Store this key securely in your client environment.
      SafeRoute never stores plaintext keys.

----------------------------------------------------------------------
Add this configuration entry to CLIENT_KEYS in your .env file:
----------------------------------------------------------------------
{
  "client_id": "mobile_app",
  "verifier": "938234e76a7ba60007f0f14532dba5cba9715e605feb4dfa3d0c415e604dee44",
  "enabled": true
}
```

---

### Configuring and Revoking Keys

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Set your `AUTH_SECRET` and register your client key verifiers in `.env`:
```env
AUTH_ENABLED=true
AUTH_SECRET="your_strong_secret_at_least_16_chars"
CLIENT_KEYS='[{"client_id": "mobile_app", "verifier": "938234e76a7ba60007f0f14532dba5cba9715e605feb4dfa3d0c415e604dee44", "enabled": true}]'
```

#### How to Revoke or Disable a Key:
- **To disable temporarily**: In `.env`, change `"enabled": true` to `"enabled": false`.
- **To revoke permanently**: Remove the client object from the `CLIENT_KEYS` array in `.env`.
- Restart the gateway for configuration changes to take effect.

---

## Ollama Provider Integration (Phase 2)

### Installing and Running Local Ollama

1. Download and install Ollama from [ollama.com](https://ollama.com).
2. Start the Ollama local daemon:
   ```bash
   ollama serve
   ```
   By default, Ollama listens at `http://localhost:11434`.

---

### Pulling a Suitable Model

For low-resource local machines, pull a lightweight model:
```bash
ollama pull llama3.2:1b
```
*(Alternative lightweight models: `phi3`, `qwen2.5:0.5b`, or `mistral`)*.

---

### Configuring the Gateway for Ollama vs. Mock

In your `.env` file, choose your active provider:

#### Option A: Running with Ollama (Local Model)
```env
ACTIVE_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:1b
ALLOWED_MODELS=llama3.2:1b,phi3,mock-model
```

#### Option B: Running with MockProvider (Deterministic, Zero-Cost Tests)
```env
ACTIVE_PROVIDER=mock
ALLOWED_MODELS=mock-model,mock-timeout,mock-error,mock-malformed
```

---

## Persistent SQLite Database & Usage Tracking (Phase 3)

### Beginner's Guide to the Database Schema

SafeRoute uses **SQLite** through **SQLAlchemy 2.0** as its persistent relational database. Unlike in-memory data that disappears whenever the server restarts, SQLite writes records to a local file on disk (`data/saferoute.db`).

The database contains four normalized tables:

1. **`clients`**:
   - Stores registered client identities (`client_id`, `created_at`, `is_active`).
   - Represents the tenant or application calling SafeRoute.
2. **`api_key_audits`**:
   - Audit trail of client credentials (`client_id`, `key_verifier_hash`, `created_at`, `is_active`).
   - Stores only SHA-256 verifiers, never plaintext keys.
3. **`request_records`**:
   - A durable log of every request that arrives at `/v1/chat/completions`.
   - Records `request_id` (unique), `client_id`, `provider`, `model`, `status_code`, `success`, `error_category`, `duration_ms` (total gateway latency), and `provider_latency_ms`.
   - Indexed on `request_id`, `client_id`, `created_at`, `provider`, and `success` for fast reporting.
   - **Privacy Guarantee**: Raw prompt text and model completions are **never stored** in the database.
4. **`usage_records`**:
   - Linked to `request_records` via a foreign key (`request_id`).
   - Stores `prompt_tokens`, `completion_tokens`, `total_tokens`, `usage_source`, `estimated_cost_usd`, and `calculation_status`.

```
+-----------------------------------------------------------+
|                          clients                          |
+-----------------------------------------------------------+
| id (PK) | client_id (UNIQUE) | is_active | created_at     |
+-----------------------------------------------------------+
                              ^
                              | 1:N (Foreign Key)
+-----------------------------------------------------------+
|                      request_records                      |
+-----------------------------------------------------------+
| id (PK) | request_id (UNIQUE) | client_id | provider ...  |
+-----------------------------------------------------------+
                              ^
                              | 1:1 (Foreign Key)
+-----------------------------------------------------------+
|                       usage_records                       |
+-----------------------------------------------------------+
| id (PK) | request_id | prompt_tokens | cost_usd ...       |
+-----------------------------------------------------------+
```

---

### Database File Location & Configuration

Configure the database connection in `.env`:

```env
# Path to SQLite database file
DATABASE_URL=sqlite:///./data/saferoute.db

# Resilient (false) vs Strict (true) mode
DATABASE_STRICT_MODE=false
```

SafeRoute automatically creates the parent directory (`data/`) upon startup if it does not already exist.

> [!NOTE]
> SQLite is configured with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`) for concurrent read/write throughput and `PRAGMA foreign_keys=ON;` on every connection to enforce relational integrity.

---

### Database Initialization, Backup, and Restore

#### 1. Automatic Initialization
The gateway automatically creates all required tables upon startup during the FastAPI lifespan hook.

#### 2. Manual Initialization / Migration
You can explicitly initialize the database schema via Python:
```bash
python -c "from app.db.session import init_db; init_db()"
```

#### 3. Online Backup
Because SQLite uses WAL mode, you can safely create an online hot backup without stopping the gateway:
```bash
sqlite3 data/saferoute.db ".backup data/saferoute_backup.db"
```

#### 4. Restore
To restore from a backup:
1. Stop the gateway.
2. Replace `data/saferoute.db` with your backup file:
   ```bash
   cp data/saferoute_backup.db data/saferoute.db
   ```
3. Restart the gateway.

---

### Database Failure Behavior (Strict vs. Resilient)

SafeRoute provides two explicitly documented failure policies via `DATABASE_STRICT_MODE`:

- **Resilient Mode (`DATABASE_STRICT_MODE=false`, default)**:
  If SQLite becomes unavailable (e.g. disk full, permission denied, locked database), SafeRoute logs an error with full context, but **does not fail the client request**. The client successfully receives their model completion.
- **Strict Mode (`DATABASE_STRICT_MODE=true`)**:
  If database persistence fails, SafeRoute immediately aborts the transaction and returns `HTTP 500` (`database_error`). Use strict mode when audited billing or regulatory compliance forbids untracked LLM usage.

---

## Token Provenance & Versioned Cost Estimation (Phase 3)

### Token Usage Provenance

Many gateways treat missing token usage as `0`, creating misleading audit trails. SafeRoute distinguishes three explicit provenance states:

1. **`provider_reported`**: Real token counts returned directly by the upstream provider (e.g. Ollama's `prompt_eval_count` and `eval_count`).
2. **`mock_estimated`**: Deterministic test values produced by `MockProvider`.
3. **`unavailable`**: Upstream provider did not supply usage data, or request failed prior to completion. Token counts are stored as `null` (None), **never** zero.

---

### Versioned Model Pricing & Decimal Arithmetic

Cloud costs are estimated using high-precision Python `Decimal` arithmetic with `ROUND_HALF_UP` quantized to 6 decimal places ($0.000001).

Pricing configurations are auditable and versioned in `app/pricing/config.json`:

$$\text{Estimated Cost} = \frac{(\text{Input Tokens} \times \text{Input Price Per 1M}) + (\text{Output Tokens} \times \text{Output Price Per 1M})}{1,000,000}$$

#### Status Codes:
- `calculated`: Successful calculation based on known tokens and price.
- `free_tier_local`: Local model inference (cost = $0.000000).
- `mock_excluded`: Mock token estimates (excluded from cloud costs).
- `missing_usage`: Tokens were unavailable.
- `unknown_model`: Model price not configured in catalog.

---

### Local Ollama & Mock Handling

- **Local Ollama (`llama3.2:1b`, etc.)**:
  Local inference incurs zero external model API charges. SafeRoute records cost as `$0.000000 USD` with calculation status `free_tier_local`.
- **MockProvider (`mock-model`, etc.)**:
  Mock estimates are flagged with `mock_excluded` and cost `null`. They are strictly excluded from all cloud-provider spending statistics.

---

## Usage Summary & CSV Export (Phase 3)

### Usage Summary Endpoint (`GET /v1/usage/summary`)

Authenticated clients can inspect their aggregated usage metrics:

```bash
curl -X GET http://127.0.0.1:8000/v1/usage/summary \
  -H "Authorization: Bearer gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8"
```

**Response (HTTP 200 OK):**
```json
{
  "client_id": "mobile_app",
  "total_requests": 42,
  "successful_requests": 40,
  "failed_requests": 2,
  "provider_calls": 40,
  "total_prompt_tokens": 1540,
  "total_completion_tokens": 820,
  "total_tokens": 2360,
  "unavailable_usage_count": 2,
  "estimated_cloud_cost_usd": 0.000000,
  "unknown_cost_count": 0,
  "avg_gateway_latency_ms": 45.2,
  "avg_provider_latency_ms": 38.1
}
```

---

### CSV Export Endpoint (`GET /v1/usage/export`)

Download complete historical audit logs as a CSV file:

```bash
curl -X GET http://127.0.0.1:8000/v1/usage/export \
  -H "Authorization: Bearer gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8" \
  -o usage_export.csv
```

---

### CLI Export Utility (`scripts/export_usage.py`)

Administrators can export records directly from the command line:

```bash
# Export all clients
python scripts/export_usage.py --output data/audit_all.csv

# Export records for a specific client
python scripts/export_usage.py --client-id mobile_app --output data/mobile_app_usage.csv
```

---

### Data Isolation & Privacy Protection

- **Tenant Isolation**: When calling `/v1/usage/summary` or `/v1/usage/export`, queries are strictly filtered by the authenticated `client_id`. No client can inspect another client's records.
- **Credential Protection**: Plaintext API keys and HMAC secrets are **never** exported.
- **Prompt Confidentiality**: Prompts and completions are not persisted in SQLite, ensuring zero leak risks in database dumps.

---

## Redis Integration & Exact-Match Response Caching (Phase 4)

### What Exact-Match Caching Does and Does Not Do

**What it does:**
- Stores successful, non-streaming chat completion responses in a Redis in-memory cache keyed deterministically.
- Returns identical cached completions when the same client submits an identical request (same model, same messages in same order, same temperature, same token limits).
- Bypasses upstream model providers on cache hits, saving compute latency and API consumption.
- Generates a fresh `X-Request-ID` and response `id` for each incoming request, ensuring request traceability.
- Accurately tracks cache hits in SQLite with `cache_status='hit'`, zero provider latency, and zero provider cloud costs.
- Communicates cache outcome via the standard `X-Cache` HTTP response header (`HIT`, `MISS`, `DISABLED`, `BYPASS`, `ERROR`).

**What it does NOT do:**
- It does **not** perform semantic similarity, fuzzy matching, or vector embeddings (scheduled for Phase 5).
- It does **not** share cached responses across different authenticated clients.
- It does **not** cache streaming requests (`stream=true`), validation errors, authentication failures, or provider outages.
- It does **not** invent token charges or fabricate upstream provider calls on cache hits.

---

### Local Redis Setup Instructions (Windows & Docker)

SafeRoute utilizes the official asynchronous Redis Python client (`redis.asyncio`). For local development on Windows, choose one of the following methods to run Redis:

#### Option A: WSL 2 (Recommended for Windows)
If you have Windows Subsystem for Linux (WSL) installed:
```bash
# Inside WSL Ubuntu terminal
sudo apt-get update
sudo apt-get install redis-server -y
sudo service redis-server start

# Verify Redis is running
redis-cli ping
# Expected output: PONG
```

#### Option B: Docker Container
If Docker Desktop is running on your machine:
```bash
# Start a local Redis 7 container mapped to standard port 6379
docker run -d --name saferoute-redis -p 6379:6379 redis:7-alpine

# Verify status
docker exec -it saferoute-redis redis-cli ping
# Expected output: PONG

# To stop when finished
docker stop saferoute-redis
```

#### Option C: Native Windows (Memurai or Redis-64)
- Download and run [Memurai](https://www.memurai.com/) (a 100% Redis-compatible server built natively for Windows).
- Memurai runs as a Windows Service listening automatically on `localhost:6379`.

---

### Configuration Variables and Defaults

Configure Redis cache settings in your `.env` file:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `REDIS_URL` | `str` | `redis://localhost:6379/0` | Redis connection URL. Supports authenticated URLs: `redis://:password@host:6379/0`. |
| `CACHE_ENABLED` | `bool` | `false` | Master cache switch. SafeRoute works completely without Redis when `false`. |
| `CACHE_TTL_SECONDS` | `int` | `300` | Expiration time-to-live for cache entries in seconds (must be positive). |
| `CACHE_NAMESPACE` | `str` | `v1` | Cache version/namespace prefix. Incrementing safely invalidates all prior entries. |
| `CACHE_FAILURE_POLICY` | `str` | `fail_open` | Outage behavior (`fail_open` falls back to provider; `fail_closed` returns HTTP 500). |

---

### Cache-Key Design & Strict Client Isolation

SafeRoute employs deterministic SHA-256 canonical hashing for cache keys:

```text
Key Format: saferoute:{namespace}:exact:{client_id}:{sha256_hash}
```

The SHA-256 hash is computed over a canonical JSON string with strictly sorted keys and compact separators:
- `namespace`: Current cache namespace (`v1`).
- `client_id`: Authenticated client identifier (guarantees cross-client isolation).
- `provider`: Resolved provider name (e.g. `mock`, `ollama`).
- `model`: Requested model name (e.g. `llama3.2:1b`).
- `messages`: Ordered list of `{"role": ..., "content": ...}` (message order is strictly preserved).
- `temperature`: Generation temperature.
- `max_completion_tokens`: Generation token limits.
- `stream`: Streaming flag.

> [!IMPORTANT]
> **Privacy Guarantee**: Cache keys contain **no raw prompt text**, completion bodies, client API keys, or authorization headers. Sensitive client prompts are never visible in Redis key names or server logs.

---

### Request Processing Order & Cache Eligibility

Each chat completion request follows a strict security-first lifecycle:

1. **Establish Request ID**: Generated uniquely by `RequestTrackingMiddleware`.
2. **Authenticate Client**: Verify HMAC-SHA256 signature; reject unauthenticated calls with HTTP 401.
3. **Validate Schema & Model Allowlist**: Reject disallowed models with HTTP 400 or oversized tokens with HTTP 422.
4. **Determine Cache Eligibility**:
   - Only eligible if `CACHE_ENABLED=true` and `request.stream=false`.
   - Streaming requests bypass cache with `X-Cache: BYPASS`.
5. **Cache Lookup**: Query Redis asynchronously using the canonical key.
6. **On Cache Hit**:
   - Reconstruct `ChatCompletionResponse` from stored JSON.
   - Assign fresh `X-Request-ID` and response `id`.
   - Record hit in SQLite (`cache_status='hit'`, zero provider latency, 0.0 incremental cost).
   - Return response with header `X-Cache: HIT`.
7. **On Cache Miss / Outage**:
   - Invoke upstream provider (Mock or Ollama).
   - On provider success: store response in Redis with configured TTL.
   - Record miss in SQLite (`cache_status='miss'`).
   - Return response with header `X-Cache: MISS` (or `ERROR` / `DISABLED`).

---

### Cache-Hit vs. Cache-Miss Behavior

| Behavior | Cache Hit (`X-Cache: HIT`) | Cache Miss (`X-Cache: MISS`) | Cache Disabled (`X-Cache: DISABLED`) |
| :--- | :--- | :--- | :--- |
| **Provider Invoked?** | **No**. Provider receives zero traffic. | **Yes**. Upstream provider is called. | **Yes**. Upstream provider is called. |
| **Provider Latency** | Recorded as `null` in SQLite. | Recorded as actual execution ms. | Recorded as actual execution ms. |
| **Gateway Latency** | Sub-millisecond (in-memory lookup). | Provider duration + network latency. | Provider duration + network latency. |
| **Response Headers** | `X-Cache: HIT` | `X-Cache: MISS` | `X-Cache: DISABLED` |
| **Request ID** | Fresh unique ID for the current request. | Fresh unique ID for the current request. | Fresh unique ID for the current request. |
| **Redis Write** | None. | Stored with TTL expiration. | None. Zero Redis interactions. |

---

### TTL & Invalidation Mechanisms

- **Finite TTL**: Every cache entry is set using Redis `SET key value EX ttl`. Once the TTL expires, Redis purges the entry automatically.
- **Client Invalidation**: Administrators can invalidate all cache entries for a specific client:
  ```python
  await cache.invalidate_client(client_id="alice")
  ```
  This uses incremental, non-blocking `SCAN` iteration (`SCAN 0 MATCH saferoute:v1:exact:alice:* COUNT 100`) rather than the blocking `KEYS *` command.
- **Namespace Invalidation**: Changing `CACHE_NAMESPACE=v2` in `.env` instantly isolates and invalidates all existing `v1` cached entries without requiring manual Redis flushes.

---

### Redis Outage & Fail-Open Behavior

SafeRoute implements a **fail-open** policy by default:
- If Redis is offline, unreachable, or times out during `GET` or `SET`, the gateway logs a structured warning and transparently falls back to invoking the AI provider.
- The request succeeds, returning the completion to the client with `X-Cache: ERROR`.
- The SQLite record logs `cache_status='error'`, preserving complete observability of the outage.
- No secrets, raw prompts, or Redis URLs with passwords are ever leaked into warning logs.

---

### SQLite Integration & Usage Accounting on Cache Hits

- **Accurate Request Accounting**: The `request_records.cache_status` field records `"hit"`, `"miss"`, `"disabled"`, `"not_applicable"`, or `"error"`.
- **Zero Incremental Cost**: Cache hits do not incur upstream provider costs. In `usage_records`, `total_cost` is recorded as `0.000000`, `calculation_status='cache_hit'`, and `usage_source='cache_hit'`.
- **No Provider Overcounting**: `GET /v1/usage/summary` does not increment `provider_counts` on cache hits, ensuring that upstream provider dashboards match gateway metrics.
- **Cache Metric Exposure**: `GET /v1/usage/summary` exposes `cache_hits` and `cache_misses` counts scoped to the authenticated client.
- **CSV Audit Export**: `GET /v1/usage/export` and `scripts/export_usage.py` include the `cache_status` column in all exported records.

---

### Security and Privacy Implications

> [!WARNING]
> **Data Storage Notice**: Enabling response caching stores completion responses in Redis memory.
> 1. **Redis is unencrypted by default**: Secure your Redis deployment using TLS, password authentication (`requirepass`), and private network boundaries.
> 2. **Never expose Redis port 6379 to the public internet**.
> 3. **Confidential completions**: If your application processes highly sensitive compliance data (HIPAA, PCI), set appropriate TTLs or keep caching disabled.
> 4. **Tenant Isolation**: Different authenticated client keys are cryptographically isolated in the cache key. Client A can never retrieve responses generated by Client B.

---

## Redis-Backed Client Rate Limiting (Phase 5)

Phase 5 introduces distributed, Redis-backed rate limiting to protect AI model providers from overuse, guarantee fair quota allocation across client applications, and defend against denial-of-service attempts.

---

### What Rate Limiting Does & Why It Is Needed

In an AI infrastructure gateway, downstream model providers (e.g., local Ollama instances or commercial cloud APIs) have finite concurrency and capacity limits. Additionally, runaway client loops or misbehaving services can quickly consume excessive GPU resources or cloud budget.

SafeRoute enforces quota limits **per authenticated client**:
- Every client identity (`client_id`) has an independent request quota within a defined time window (e.g., 60 requests per 60 seconds).
- Valid requests within the quota proceed normally, receiving standard `X-RateLimit-*` diagnostic headers.
- When a client exceeds their allowance, subsequent requests are immediately rejected by the gateway with **HTTP 429 Too Many Requests** and a `Retry-After` header.
- Rejections occur at the edge of the gateway **before** invoking AI providers or consulting the response cache, conserving resources and budget.

---

### Atomic Fixed-Window Algorithm & Lua Script

SafeRoute implements an **atomic Redis fixed-window counter** using an embedded Lua script.

#### Why Atomic Lua Execution is Required
In a multi-worker deployment (e.g., Uvicorn running multiple processes behind a load balancer), naive rate limiting with separate Redis `INCR` and `EXPIRE` commands introduces a critical race condition:
1. Process A calls `INCR key`.
2. The network disconnects or Process A crashes before executing `EXPIRE key 60`.
3. The counter key is left in Redis with **no TTL** (infinite lifespan), permanently locking the client out.

Furthermore, naive implementations often call `EXPIRE` on every request, resetting the window and preventing the client's counter from ever expiring during active traffic.

#### Lua Script Implementation
SafeRoute resolves this atomically inside Redis:
```lua
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
if ttl == -1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
end
return {current, ttl}
```

**Guarantees provided:**
1. **Zero Race Conditions**: The counter creation and TTL initialization execute in a single atomic transaction inside Redis.
2. **Stable Expiration**: Subsequent requests increment the counter without modifying or extending the remaining TTL.
3. **Multi-Worker Safety**: Multiple gateway instances share identical atomic Redis state without relying on local in-memory counters.
4. **Resilient Recovery**: If an unexpired key has a `-1` TTL (edge case), it is immediately given an expiration.

---

### Algorithm Trade-Offs & Limitations

| Aspect | Fixed-Window Counter (Phase 5) | Sliding-Window / Token-Bucket |
| :--- | :--- | :--- |
| **Complexity & Memory** | **Minimal**: Single atomic integer key per client with native Redis TTL. | High: Requires Redis sorted sets (ZSET) or token replenishment timestamps. |
| **Performance** | **Sub-millisecond**: Single round-trip atomic script execution. | Multiple round-trips or heavier data structures. |
| **Boundary Bursting** | **Trade-off**: A client can make $N$ requests at the end of Window 1 ($t = 59s$) and $N$ requests at the start of Window 2 ($t = 61s$), allowing $2N$ requests across a 2-second interval spanning the boundary. | Smoothly meters requests over continuous intervals without boundary bursts. |

*Limitation Summary*: The fixed-window algorithm provides high throughput and operational simplicity. For applications where strict boundary smoothing is required, sliding-window log algorithms are scheduled for future exploration.

---

### Configuration Variables and Defaults (Phase 5)

Rate limiting is fully configurable in `.env` without code modifications:

| Environment Variable | Default | Type | Description |
| :--- | :--- | :--- | :--- |
| `RATE_LIMIT_ENABLED` | `false` | Boolean | Master switch. Disabled by default until explicitly activated by the operator. |
| `RATE_LIMIT_REQUESTS` | `60` | Integer | Allowed requests per window (must be greater than 0). |
| `RATE_LIMIT_WINDOW_SECONDS`| `60` | Integer | Window duration in seconds (must be greater than 0). |
| `RATE_LIMIT_NAMESPACE` | `v1` | String | Namespace prefix for Redis keys. Incrementing safely purges old quotas. |
| `RATE_LIMIT_FAILURE_POLICY`| `fail_closed` | String | Behavior when Redis is unreachable: `fail_closed` (secure default) or `fail_open`. |

#### Per-Client Overrides
Operators can specify custom rate limits for individual clients within the `CLIENT_KEYS` configuration without breaking gateway defaults:
```json
[
  {
    "client_id": "vip_service",
    "verifier": "<sha256_hash>",
    "rate_limit_requests": 500,
    "rate_limit_window_seconds": 60,
    "enabled": true
  },
  {
    "client_id": "free_tier_app",
    "verifier": "<sha256_hash>",
    "rate_limit_requests": 10,
    "rate_limit_window_seconds": 60,
    "enabled": true
  }
]
```

---

### Client Identity & Cryptographic Isolation

- **Authentication-Derived Identity**: The rate limiter strictly uses the `client_id` established by gateway HMAC-SHA256 authentication.
- **Header Spoofing Prevention**: Client-supplied headers (e.g. `X-Client-ID`, `X-Forwarded-For`, `Client-Identity`) are **never trusted** as rate-limiting identities.
- **Redis Key Construction**: Deterministic Redis keys are formed as:
  ```text
  saferoute:{namespace}:ratelimit:{client_id}
  ```
  Example: `saferoute:v1:ratelimit:mobile_app`
- **Privacy Assurance**: Redis rate limit keys never contain raw API keys, bearer tokens, model prompts, or completion text.

---

### HTTP 429 Too Many Requests & Headers

When a client makes requests within quota, SafeRoute returns HTTP 200 with diagnostics:
```http
HTTP/1.1 200 OK
X-Request-ID: req_a8f921d37b6045d3bc64e231ef634ab1
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 59
X-RateLimit-Reset: 58
```

When quota is exhausted, SafeRoute responds immediately with:
```http
HTTP/1.1 429 Too Many Requests
Retry-After: 42
X-Request-ID: req_c40156d8e20b4ec79522858d4a4fe80f
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 42
Content-Type: application/json
```

**Structured JSON Error Body:**
```json
{
  "error": {
    "type": "requests",
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Allowed: 60 requests per window. Please retry after 42 seconds.",
    "request_id": "req_c40156d8e20b4ec79522858d4a4fe80f"
  }
}
```

---

### Redis Outage Behavior (Fail-Closed vs. Fail-Open)

Rate limiting is an active security control. If Redis crashes or network connectivity is severed:

1. **`fail_closed` (Default & Recommended)**:
   - Rejects incoming completion requests with **HTTP 503 Service Unavailable** (`error_code="rate_limiter_unavailable"`).
   - Protects downstream AI models and GPUs from being overwhelmed during infrastructure degradation.
   - Distinct from HTTP 429: Clients receive a service-unavailable signal rather than a false quota-exceeded message.
2. **`fail_open` (Operator-Configured Option)**:
   - Logs a warning with sanitized URLs (no credentials leaked) and allows requests through to the provider.
   - Used when uptime is prioritized over quota enforcement.

---

### Interaction with Cache Hits, Provider Calls, and Safety Checks

The request lifecycle is strictly ordered to prevent quota abuse and unnecessary consumption:

1. **Request ID Assigned**: Fresh `X-Request-ID` generated or sanitized.
2. **Authentication Verified**: Missing or invalid API keys return HTTP 401 **without consuming quota**.
3. **Payload & Model Validation**: Model allowlist violations (HTTP 400), message count limits (HTTP 400), and max tokens limit violations (HTTP 422) fail **before quota is checked**. A client is never penalized for rejected schemas.
4. **Rate Limit Evaluated**: Quota is checked against Redis.
5. **Exact Cache Evaluated**:
   - **Cache Hits Count Toward Quota**: A client cannot bypass rate limits by repeating cached queries.
   - If quota is exceeded, the cached response is **not returned**; HTTP 429 is returned.
6. **Provider Invocation**: Upstream AI providers are only called if the request is within quota and misses the cache. Rate-limited requests **never** invoke the provider.
7. **Public Probes Exempt**: Health (`GET /health`) and readiness (`GET /ready`) probes bypass rate limiting completely.

---

### SQLite Request & Usage Accounting

Rate-limited rejections are fully observable and durably recorded in SQLite:
- `request_records`: Stored with `http_status=429`, `status='failed'`, `error_code='rate_limit_exceeded'`, `provider='gateway'`, and `cache_status='not_applicable'`.
- `usage_records`: Recorded with `null` token counts, `null` costs, and `usage_source='unavailable'`. Rate-limited requests **never produce fake tokens or costs**.
- `GET /v1/usage/summary`: Counts 429 rejections in `total_requests` and `failed_requests` while keeping `provider_counts` accurate.

---

## Configurable Input and Output Guardrails (Phase 6)

### What Guardrails Do & Why They Are Needed

An LLM gateway acts as a security boundary between client applications and model backends. While Large Language Models are capable of processing complex requests, production enterprise environments require deterministic guardrails to:
1. **Prevent Dangerous Commands**: Block malicious administrative operations (e.g., SQL drops, system injection patterns) before reaching AI systems.
2. **Enforce Corporate Data Policies**: Prevent sensitive internal identifiers or prohibited terms from being submitted to model providers.
3. **Intercept Prohibited Provider Output**: Catch unwanted terms, internal test fixtures, or sensitive strings in model completions before they reach client applications or are saved in shared response caches.
4. **Maintain Auditable Compliance**: Record all policy violation attempts in durable SQLite records with stable reason codes without exposing sensitive client data.

---

### Deterministic Rule Matching vs. Semantic AI Safety

> [!WARNING]
> **Deterministic Pattern Matching Limitations**:
> Phase 6 introduces a deterministic, rule-based guardrail layer using exact substrings, word boundaries, and pre-compiled regular expressions.
>
> **What This Layer Can Detect**:
> - Known blocked keywords and phrases (e.g. `DROP DATABASE`, prohibited internal tokens).
> - Specific structured patterns via regular expressions (e.g. test credential formats, restricted command signatures).
> - Target-stage filtering (inspecting inputs, outputs, or both).
>
> **What This Layer Cannot Detect**:
> - Sophisticated prompt injection attacks (e.g. adversarial indirect injection, semantic roleplay bypasses, Base64/rot13 obfuscation, l33tspeak).
> - Unstructured personal identifiable information (PII) without explicit regex definitions.
> - Subtle toxic, defamatory, or harmful content that lacks explicitly matched keywords.
> - Paraphrased or multilingual policy violations.
>
> Deterministic rules serve as a high-speed, zero-cost operational perimeter. Semantic AI safety classification (using specialized classifier models and embeddings) is an independent capability scheduled for future architectural phases.

---

### Configuration Variables & Safe Defaults (Phase 6)

Guardrails are configured through environment variables or `.env` files:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `GUARDRAILS_ENABLED` | `bool` | `false` | Master toggle. SafeRoute operates without guardrail overhead when `false`. |
| `GUARDRAILS_INPUT_ENABLED` | `bool` | `true` | Enables inspection on client input messages when guardrails are enabled. |
| `GUARDRAILS_OUTPUT_ENABLED` | `bool` | `true` | Enables inspection on provider completions and cached completions. |
| `GUARDRAILS_ACTION` | `str` | `block` | Enforcement action when a rule matches. Currently supported: `block`. |
| `GUARDRAILS_MAX_TEXT_LENGTH` | `int` | `100000` | Maximum character length evaluated per message turn / completion text (ReDoS bound). |
| `GUARDRAILS_RULES` | `list[dict]` | `[]` | JSON array or Python list of rule definitions evaluated deterministically. |

---

### Rule Definition Format & Match Types

Guardrail rules are defined as a JSON array of rule dictionaries. Each rule supports the following schema:

```json
[
  {
    "rule_id": "block_drop_database",
    "pattern": "DROP\\s+DATABASE",
    "match_type": "regex",
    "stage": "both",
    "case_sensitive": false
  },
  {
    "rule_id": "block_prohibited_secret",
    "pattern": "SECRET_KEY_PROHIBITED",
    "match_type": "contains",
    "stage": "both",
    "case_sensitive": true
  },
  {
    "rule_id": "block_system_override_keyword",
    "pattern": "override_safety",
    "match_type": "keyword",
    "stage": "input",
    "case_sensitive": false
  }
]
```

#### Supported Fields:
- **`rule_id`** (`str`, required): Unique identifier for the rule. Used in structured audit logs and database error records.
- **`pattern`** (`str`, required): The pattern string or regular expression to match against.
- **`match_type`** (`str`, optional, default `"regex"`):
  - `"regex"`: Full Python regular expression matching.
  - `"contains"`: Fast substring search (`pattern in content`).
  - `"keyword"`: Word-boundary matching using regex `\bpattern\b`.
- **`stage`** (`str`, optional, default `"both"`):
  - `"input"`: Evaluated only against incoming client message turns.
  - `"output"`: Evaluated only against upstream provider completions and cached completions.
  - `"both"`: Evaluated at both input and output stages.
- **`case_sensitive`** (`bool`, optional, default `false`): When `false`, matches case-insensitively.

---

### Startup Validation & ReDoS Protection

SafeRoute enforces strict startup validation and runtime protections:
1. **Fail-Fast Regex Validation**: All regex patterns in `GUARDRAILS_RULES` are validated and pre-compiled during gateway startup (`Settings` validation). If a rule contains a malformed regex (such as unmatched parentheses `(`), the gateway aborts startup immediately with a clear configuration error.
2. **ReDoS (Regular Expression Denial of Service) Protection**: Pathological inputs designed to trigger catastrophic regex backtracking are mitigated via `GUARDRAILS_MAX_TEXT_LENGTH` (default: 100,000 characters). Messages exceeding this bound are safely intercepted before regex evaluation, returning a documented error code `processing_limit_exceeded`.

---

### Input Inspection & Rate Limit Interaction

When an authenticated client submits a chat completion request, the gateway enforces the following lifecycle:

1. **Authentication Verified**: Missing or invalid credentials return HTTP 401 **without running guardrails or consuming rate-limit quota**.
2. **Schema & Model Allowed**: Disallowed models (HTTP 400) or oversized message counts (HTTP 400) fail before rate limits and guardrails.
3. **Rate Limit Checked**: The client's rate-limiting quota is evaluated.
4. **Input Guardrail Inspection**: Each message turn in `request.messages` is evaluated in sequential order:
   - If any message violates a configured input rule, SafeRoute **aborts the request immediately** with **HTTP 400 Bad Request** (`error_code="input_guardrail_blocked"`).
   - **No Provider Invocation**: Upstream AI providers are never called.
   - **No Cache Access**: Blocked inputs are never checked or served from the Redis cache.
   - **Rate Limit Quota Consumed**: Blocked inputs consume 1 quota slot from the authenticated client's rate limit window, preventing malicious clients from flooding the gateway with free unmetered guardrail probes.
   - **Durable SQLite Record**: Recorded with `http_status=400`, `status='failed'`, `error_code='input_guardrail_blocked'`, and `null` token usage.

---

### Output Inspection, Stale Cache Invalidation & Usage Accounting

When an upstream provider returns a successful completion, or when an exact cache lookup succeeds:

1. **Provider Completion Inspection**:
   - Each choice message content (`choices[i].message.content`) is inspected against output-eligible guardrail rules.
   - If an output violates a rule, the completion is **blocked**:
     - **HTTP 502 Bad Gateway** is returned to the client (`error_code="output_guardrail_blocked"`).
     - The blocked completion text is **never stored in the Redis cache**.
     - The blocked completion text is **never returned to the client**.
     - **Truthful Usage Accounting**: Because the upstream provider was physically invoked and consumed real GPU/cloud resources, actual provider token counts, provider latency, and calculated costs are **durably recorded in SQLite** with `status='failed'` and `error_code='output_guardrail_blocked'`. Usage data is never zeroed or fabricated.
2. **Stale Cache Invalidation on Cache Hits**:
   - If a response was cached in Redis under a previous policy, but newly introduced output guardrails now prohibit that response, SafeRoute **inspects cached choices upon lookup**.
   - If a cached completion violates current output policy:
     - SafeRoute **immediately deletes and invalidates the stale cache entry from Redis**.
     - Returns **HTTP 502 Bad Gateway** (`error_code="output_guardrail_blocked"`).
     - Records the cache hit failure in SQLite (`cache_status='hit'`, zero provider latency, zero cost).

---

### Privacy & Structured Audit Logging

To comply with enterprise data security and privacy regulations:
- **No Prompt or Completion Leakage**: Guardrail log messages and rejection responses never output the raw prompt, user message text, or prohibited completion content.
- **No Secret or Regex Exposure**: Internal regex patterns and rule implementation details are never included in client-facing error payloads.
- **Structured Audit Metadata**: Logs and audit records capture safe operational telemetry:
  - `request_id`: Traced correlation ID.
  - `client_id`: Authenticated client identity.
  - `stage`: `"input"` or `"output"`.
  - `rule_id`: Identifier of the matched rule (e.g. `block_drop_database`).
  - `reason_code`: `"blocked_by_rule"` or `"processing_limit_exceeded"`.
  - `action`: `"block"`.

---

## Reproducible Evaluation and Benchmarking Framework (Phase 7)

### What the Evaluation Framework Measures

To guarantee that SafeRoute behaves reliably under production workloads, Phase 7 introduces a reproducible, versioned evaluation and performance benchmarking framework. It answers critical operational questions with empirical evidence:

1. **Exact-Match Caching Latency**: Does exact-match caching measurably reduce response times? (Demonstrated: warm cache hits reduce response times by bypassing provider execution).
2. **Provider Call Avoidance**: Does a cache hit reliably prevent redundant upstream provider calls and cloud token expenditure?
3. **Accounting & Usage Integrity**: Are request counts, actual token usage, and versioned cost calculations recorded accurately in SQLite? Are missing tokens kept as `null` rather than converted to misleading zeros?
4. **Rate Limiting Accuracy**: Does the atomic Redis rate limiter strictly permit requests within quota and reject excess requests with HTTP 429 and `Retry-After` headers?
5. **Deterministic Guardrail Enforcement**: Do input rules intercept prohibited prompt turns before providers are contacted? Do output rules prevent prohibited completions from reaching the client or the cache?
6. **Provider Outage & Timeout Resilience**: How does the gateway handle upstream errors and timeouts? Are errors properly normalized to standard HTTP 502 and HTTP 504 responses without exposing stack traces?
7. **Redis Degradation Behavior**: Does the gateway respect `fail_closed` (HTTP 503) and `fail_open` (transparent fallback to provider with `X-Cache: ERROR`) policies when Redis is unavailable?
8. **Gateway Component Overhead**: How many milliseconds of processing overhead does the gateway introduce across routing, authentication, guardrail inspection, and database auditing?

---

### Versioned Evaluation Dataset Format

Evaluation cases are defined in a versioned JSON dataset: [`datasets/evaluation/default_suite.json`](file:///d:/SafeRoute%20LLM%20Gateway/datasets/evaluation/default_suite.json). Each case specifies an isolated scenario, required configuration overrides, request parameters, and expected outcome assertions:

```json
{
  "dataset_id": "saferoute_core_evaluation_v1",
  "version": "1.0.0",
  "description": "Standard deterministic evaluation suite for SafeRoute LLM Gateway...",
  "cases": [
    {
      "case_id": "eval_01_ordinary_success",
      "category": "standard_completion",
      "description": "Ordinary valid chat completion request using MockProvider returns HTTP 200 with choices and estimated usage.",
      "scenario_type": "single_request",
      "requires_live": false,
      "setup": {
        "auth_enabled": true,
        "cache_enabled": false,
        "rate_limit_enabled": false,
        "guardrails_enabled": false
      },
      "request": {
        "endpoint": "/v1/chat/completions",
        "method": "POST",
        "auth": "valid",
        "body": {
          "model": "mock-model",
          "messages": [{"role": "user", "content": "What is Python?"}]
        }
      },
      "expected": {
        "status_code": 200,
        "has_choices": true,
        "usage_present": true,
        "is_mock_estimate": true
      }
    }
  ]
}
```

#### Supported Scenario Types:
- **`single_request`**: Executes a single HTTP call against the gateway and validates status code, error code, headers, and payload structure.
- **`sequential_cache_hit`**: Executes two consecutive identical requests: confirms request #1 produces a cache miss (`X-Cache: MISS`), and request #2 produces a warm cache hit (`X-Cache: HIT`) with reduced latency.
- **`rate_limit_burst`**: Emits requests up to the configured limit (verifying HTTP 200), followed by an $(N+1)$-th request (verifying HTTP 429 and `rate_limit_exceeded`).
- **`redis_outage`**: Simulates a Redis network partition and verifies that the gateway enforces the configured outage policy (`fail_closed` or `fail_open`).

---

### Running a Quick Local Evaluation

The quick evaluation mode runs all 14 core functional evaluation test cases against deterministic offline test doubles in under 2 seconds:

```powershell
python scripts/run_evaluation.py --mode quick
```

**Output Preview:**
```text
============================================================================
SafeRoute LLM Gateway — Evaluation & Benchmarking Harness
Dataset Path : D:\SafeRoute LLM Gateway\datasets\evaluation\default_suite.json
Runner Mode  : quick
Live Services: DISABLED (Mock doubles only)
============================================================================
Loaded dataset 'saferoute_core_evaluation_v1' (v1.0.0): 15 test cases.

Executing Evaluation Cases:
----------------------------------------------------------------------------
[PASS] eval_01_ordinary_success         ( 89.72ms)
[PASS] eval_02_invalid_schema           ( 38.71ms)
[PASS] eval_03_unauthorized_key         ( 33.40ms)
[PASS] eval_04_revoked_key              ( 30.25ms)
[PASS] eval_05_unsupported_model        ( 43.51ms)
[PASS] eval_06_input_guardrail_block    ( 55.06ms)
[PASS] eval_07_output_guardrail_block   ( 59.86ms)
[PASS] eval_08_provider_timeout         (160.95ms)
[PASS] eval_09_provider_error           ( 54.51ms)
[PASS] eval_10_cache_miss_and_hit       ( 52.15ms)
[PASS] eval_11_rate_limit_rejection     ( 55.07ms)
[PASS] eval_12_redis_unavailable_fail_closed ( 52.14ms)
[PASS] eval_13_redis_unavailable_fail_open ( 49.19ms)
[PASS] eval_14_unknown_model_pricing    ( 44.07ms)
[SKIP] eval_15_live_ollama_optional     (  0.00ms) -> Requires live external service (Ollama or Redis). Re-run with --live to execute.
----------------------------------------------------------------------------

============================================================================
Evaluation Summary:
  Total Cases : 15
  Passed      : 14
  Failed      : 0
  Skipped     : 1
  Errored     : 0
  Pass Rate   : 100.0%
  Duration    : 862.47 ms
----------------------------------------------------------------------------
JSON Report : D:\SafeRoute LLM Gateway\data\evaluation_results\eval_1c55c8e1855c.json
Markdown    : D:\SafeRoute LLM Gateway\data\evaluation_results\eval_1c55c8e1855c.md
============================================================================
```

---

### Running a Full Evaluation with Performance Benchmarks

The full evaluation mode runs all functional test cases plus automated performance micro-benchmarks across cold/warm cache, baseline execution, guardrail inspection overhead, and provider error handling:

```powershell
python scripts/run_evaluation.py --mode full --benchmark-iterations 20
```

**Benchmark Results Table:**
```text
----------------------------------------------------------------------------
Scenario                     Hit Ratio    Mean (ms)  p50 (ms)   Throughput
----------------------------------------------------------------------------
warm_cache_hits              95.0%        8.69       7.91       108.26 rps
cache_disabled_baseline      N/A          8.61       7.30       110.11 rps
guardrails_active_overhead   N/A          8.61       7.62       109.32 rps
provider_error_handling      N/A          8.77       8.42       108.24 rps
----------------------------------------------------------------------------
```

---

### Interpreting Evaluation & Benchmark Metrics

The performance benchmarker reports high-precision statistics calculated using Python's monotonic clock (`time.perf_counter()`):

| Metric | Description | How to Interpret |
| :--- | :--- | :--- |
| **Hit Ratio** | Ratio of requests served from cache (`hits / total_samples`). | In `warm_cache_hits`, request #1 is a cold miss while requests 2..$N$ are hits ($>90\%$). |
| **Mean (ms)** | Arithmetic mean of total round-trip request latency. | Overall average gateway latency. |
| **p50 (ms)** | Median latency (50th percentile). | Typical latency experienced by half of the requests. |
| **p95 (ms)** | 95th percentile latency. | Tail latency experienced under occasional spikes. |
| **p99 (ms)** | 99th percentile latency. | Worst-case tail latency. |
| **Throughput (rps)** | Completed requests per second. | Sequential throughput capacity per gateway worker. |

---

### Mock Doubles vs. Live External Services

To enable instantaneous local runs without requiring a GPU, external API accounts, or background Redis services:
- **Default Mode (`--live` not set)**: Uses deterministic in-memory test doubles:
  - `MockProvider`: Simulates deterministic completions and token counts in memory.
  - `FakeEvalRedis`: Simulates Redis exact caching with string storage and simulated outages.
  - `FakeEvalLimiterRedis`: Simulates Redis atomic Lua fixed-window counter scripts.
  - Case `eval_15_live_ollama_optional` is safely marked as **SKIPPED** (not failed).
- **Live Mode (`--live`)**: Instructs the runner to execute live service cases against active services (such as a local Ollama server running at `http://localhost:11434` or live Redis on port 6379).

---

### Report Generation & Safe Artifact Storage

Every evaluation run automatically generates two auditable report files in `data/evaluation_results/`:
1. **Machine-Readable JSON (`eval_{run_id}.json`)**: Contains full structured metadata, pass/fail status, duration per case, and detailed benchmark metric dictionaries. Ideal for CI/CD pipeline parsing.
2. **Human-Readable Markdown (`eval_{run_id}.md`)**: A GitHub-flavored Markdown document with summary tables, pass/fail badges, and benchmark comparison grids.

> [!IMPORTANT]
> **Data Security Guarantee**:
> In compliance with enterprise privacy standards, evaluation reports **never store client API keys, Authorization headers, database connection credentials, or raw prompt text**.
> All evaluation result files in `data/evaluation_results/` are excluded by `.gitignore` to prevent committing test artifacts to the repository.

---

### Statistical Caution & Limitations

> [!CAUTION]
> **Benchmarking Limitations**:
> 1. **Sample Size**: Default benchmark runs use 10–20 iterations to remain fast. While sufficient for indicative developer comparisons, small samples are not statistically conclusive for formal production SLAs.
> 2. **Mock Latency vs. Real LLM Inference**: In-memory mock completions execute in sub-milliseconds. Benchmark numbers measure **gateway internal routing and caching overhead**, not upstream neural network inference time.
> 3. **Concurrency**: Default micro-benchmarks run sequentially to isolate algorithmic overhead without thread contention noise.

---

## Running the Gateway

Start the application with Uvicorn:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The gateway will be available at `http://127.0.0.1:8000`. Interactive documentation is available at `http://127.0.0.1:8000/docs`.

---

## API Reference & Examples

### Liveness Check (`GET /health`)
Public endpoint. Returns operational status.

```bash
curl -X GET http://127.0.0.1:8000/health
```

**Response (HTTP 200 OK):**
```json
{
  "status": "ok",
  "app": "SafeRoute LLM Gateway",
  "environment": "development"
}
```

---

### Readiness Check (`GET /ready`)
Public endpoint. Verifies that active providers are reachable.

```bash
curl -X GET http://127.0.0.1:8000/ready
```

**Response (HTTP 200 OK):**
```json
{
  "status": "ready",
  "providers": {
    "mock": "available"
  }
}
```

---

### Authenticated Chat Completion (`POST /v1/chat/completions`)

Requires `Authorization: Bearer <gateway_api_key>`.

```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:1b",
    "messages": [
      {
        "role": "system",
        "content": "You are a concise assistant."
      },
      {
        "role": "user",
        "content": "Explain what an LLM gateway is in one sentence."
      }
    ],
    "temperature": 0.3,
    "max_completion_tokens": 100,
    "stream": false
  }'
```

**Response (HTTP 200 OK):**
```json
{
  "id": "chatcmpl-ollama-9f81a7b4c2d3",
  "object": "chat.completion",
  "created": 1792866000,
  "model": "llama3.2:1b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "An LLM gateway is a reverse proxy that centralizes security, routing, and monitoring between applications and AI models."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 28,
    "completion_tokens": 24,
    "total_tokens": 52,
    "is_mock_estimate": false,
    "usage_source": "provider_reported"
  }
}
```

*Response Header:* `X-Request-ID: req_8c1b827e8a324ab2a61bb819c9e83f21`

---

### Usage Statistics (`GET /v1/usage/summary`)

Requires `Authorization: Bearer <gateway_api_key>`.

```bash
curl -X GET http://127.0.0.1:8000/v1/usage/summary \
  -H "Authorization: Bearer gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8"
```

**Response (HTTP 200 OK):**
```json
{
  "client_id": "mobile_app",
  "total_requests": 42,
  "successful_requests": 40,
  "failed_requests": 2,
  "provider_calls": 40,
  "total_prompt_tokens": 1540,
  "total_completion_tokens": 820,
  "total_tokens": 2360,
  "unavailable_usage_count": 2,
  "estimated_cloud_cost_usd": 0.000000,
  "unknown_cost_count": 0,
  "avg_gateway_latency_ms": 45.2,
  "avg_provider_latency_ms": 38.1
}
```

---

### Usage Export (`GET /v1/usage/export`)

Requires `Authorization: Bearer <gateway_api_key>`. Downloads a CSV audit file.

```bash
curl -X GET http://127.0.0.1:8000/v1/usage/export \
  -H "Authorization: Bearer gw_test_K_3j1nOxRuqXlIbZ8lumcq4d81l0oOe66UUujUfuWu8" \
  -o usage_export.csv
```

---

### Authentication & Validation Error Responses

#### 1. Missing Authorization Header (HTTP 401)
```json
{
  "error": {
    "type": "authentication_error",
    "code": "invalid_api_key",
    "message": "Missing Authorization header.",
    "request_id": "req_1d4a0765c92849e7b270a6c22c0e7fb8"
  }
}
```

#### 2. Invalid or Forged Key (HTTP 401)
```json
{
  "error": {
    "type": "authentication_error",
    "code": "invalid_api_key",
    "message": "Invalid client API key.",
    "request_id": "req_79c13b2c286d49959600a943a4e98f02"
  }
}
```

#### 3. Disabled or Revoked Key (HTTP 401)
```json
{
  "error": {
    "type": "authentication_error",
    "code": "invalid_api_key",
    "message": "Client API key is disabled or revoked.",
    "request_id": "req_88a6d41ef42144d49a37a9a9572c679a"
  }
}
```

#### 4. Upstream Ollama Service Unreachable (HTTP 502)
```json
{
  "error": {
    "type": "bad_gateway_error",
    "code": "provider_error",
    "message": "Upstream Ollama service is unreachable or not running.",
    "request_id": "req_9971ab01e91942e6a9f4c330df320ba1"
  }
}
```

#### 5. Client Exceeded Rate Limit (HTTP 429)
Returned when an authenticated client exceeds their allowed quota (`RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS`).
Headers include `Retry-After: 42`, `X-RateLimit-Limit: 60`, `X-RateLimit-Remaining: 0`, and `X-RateLimit-Reset: 42`.
```json
{
  "error": {
    "type": "requests",
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Allowed: 60 requests per window. Please retry after 42 seconds.",
    "request_id": "req_c40156d8e20b4ec79522858d4a4fe80f"
  }
}
```

#### 6. Redis Rate Limiter Unavailable (HTTP 503)
Returned when Redis is unreachable and `RATE_LIMIT_FAILURE_POLICY=fail_closed` is active.
```json
{
  "error": {
    "type": "service_unavailable_error",
    "code": "rate_limiter_unavailable",
    "message": "Rate limiter service is temporarily unavailable. Request rejected per fail-closed policy.",
    "request_id": "req_e123456789abcdef0123456789abcdef"
  }
}
```

### Guardrail Rejection Error Responses

#### 7. Input Guardrail Blocked (HTTP 400)
Returned when client input message content matches a configured input guardrail rule or exceeds the maximum processing length limit.
Rate-limit quota is consumed to prevent unmetered gateway probing; upstream providers are never invoked.
```json
{
  "error": {
    "type": "invalid_request_error",
    "code": "input_guardrail_blocked",
    "message": "Request content was blocked by input safety guardrails.",
    "request_id": "req_f4a13b6241b248a39e802b525890e1a2"
  }
}
```

#### 8. Output Guardrail Blocked (HTTP 502)
Returned when an upstream provider completion (or a cached completion) violates a configured output guardrail rule.
The response text is withheld from the client and will not be cached in Redis. Actual provider token usage and latency are preserved in SQLite audit records.
```json
{
  "error": {
    "type": "bad_gateway_error",
    "code": "output_guardrail_blocked",
    "message": "Provider response was blocked by output safety guardrails.",
    "request_id": "req_c872d80ef74a4cf0b299e7421c437148"
  }
}
```

---

## Running Tests

Execute the automated test suite with `pytest`:

```bash
pytest -v
```

> [!NOTE]
> **No Live Redis or Ollama Required for Tests**: The automated test suite (all 164 tests) uses SQLite in-memory databases, HTTP mock transports, and deterministic async Redis test doubles (`FakeAsyncRedis` and `FakeAsyncRedisForLimiter`). Running `pytest -v` does **not** require an active Redis daemon or local Ollama server.
>
> **Live Redis Verification Status**: Testing live Redis network connections requires starting a local Redis instance on port 6379 and setting `RATE_LIMIT_ENABLED=true` or `CACHE_ENABLED=true` in `.env`. In this development environment, live Redis verification is currently **pending** because no active Redis daemon was reachable at `localhost:6379`. All rate limiting, Lua script atomicity, boundary conditions, client isolation, guardrail enforcement, and evaluation runner behaviors have been verified through automated in-memory Redis test fixtures.

Expected result:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-8.3.4
rootdir: D:\SafeRoute LLM Gateway
configfile: pyproject.toml
396 passed, 3 skipped in 50.16s
======================== 396 passed, 3 skipped in 50.16s ========================
```

---

## Phase 8: Architecture Simplification & Focused Local Runtime

SafeRoute LLM Gateway is designed as a focused, lightweight, and maintainable gateway optimized for **local Ollama runtimes** and deterministic testing via **MockProvider**.

### Architectural Overview

SafeRoute sits between client applications and your local inference infrastructure:
1. **OpenAI-Compatible Ingress**: Clients interact exclusively with the standard `/v1/chat/completions` endpoint using standard OpenAI payloads.
2. **Deterministic Security Pipeline**: Requests undergo HMAC-SHA256 client authentication, timing-safe key verification, character-length sanity bounds, and input safety guardrails.
3. **Multi-Tier Caching**: Eligible requests hit the Level 1 exact Redis cache or Level 2 semantic cache, bypassing model inference with zero-cost provenance.
4. **Local Runtime Execution**: Primary inference is routed asynchronously to a local **Ollama** server (`POST /api/chat`), supporting model streaming, tool calling, and health monitoring.
5. **Deterministic Testing**: `MockProvider` provides instantaneous, cost-free in-memory responses and exact failure simulation (timeouts, rate limits, malformed payloads) for development and CI testing.
6. **Durable Persistence & Metrics**: Outcomes, token counts, latencies, and cache states are recorded in persistent SQLite with WAL mode, and Prometheus metrics are incremented.

> **Cleanup Note**: External cloud providers (**Anthropic Claude** and **Google Gemini**) were audited and removed from the active gateway to eliminate unnecessary complexity, cloud API dependencies, recurring billing risks, and external credential management. Historical pricing records and model capabilities are retained as reference entries so existing database records remain 100% computable and intact.

### Provider Configuration & Selection

SafeRoute supports two clean runtime modes:

- `ACTIVE_PROVIDER=ollama`: Routes completion requests to your local Ollama daemon (default base URL: `http://localhost:11434` or Docker `http://host.docker.internal:11434`).
- `ACTIVE_PROVIDER=mock`: Routes completion requests to the in-memory MockProvider test harness for offline unit testing, benchmark evaluation, and mock tool calling.

#### Environment Variables (.env)

```env
# Global provider selection: "ollama" (primary) or "mock" (testing)
ACTIVE_PROVIDER=ollama

# Ollama Local Runtime Configuration
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_MODEL=llama3.2:1b
PROVIDER_TIMEOUT_SECONDS=30.0

# Permitted Active Models
ALLOWED_MODELS=llama3.2:1b,qwen2.5-coder:7b-instruct-q4_K_M,llama3.2,phi3,mistral,mock-echo,mock-chat,mock-rate-limit,mock-timeout,mock-streaming
```

### Running Tests Without Cloud Credentials

All test suites and unit tests run completely offline and require **zero cloud API credentials**:

```powershell
# Run the complete test suite
python -m pytest -q

# Run specific provider tests
python -m pytest tests/unit/test_ollama_provider.py tests/integration/test_ollama_integration.py -v
```

### Running Local Ollama Requests (PowerShell)

```powershell
# 1. Start the gateway locally on Windows
python -m uvicorn app.main:app --port 8000

# 2. In another PowerShell terminal, query Ollama via standard SafeRoute completions:
$headers = @{
    "Authorization" = "Bearer gw_test_your_client_key_here"
    "Content-Type"  = "application/json"
}
$body = @{
    model = "llama3.2:1b"
    messages = @(
        @{ role = "user"; content = "Hello Ollama, verify you are live via SafeRoute!" }
    )
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/v1/chat/completions" -Method Post -Headers $headers -Body $body
```

---

### Streaming Chat Completions (Phase 9.2)

To stream tokens incrementally, pass `"stream": true` in the request body. SafeRoute returns `Content-Type: text/event-stream; charset=utf-8` using the OpenAI-compatible Server-Sent Events (SSE) format.

#### PowerShell Example
```powershell
$headers = @{
    "Authorization" = "Bearer gw_test_your_client_key_here"
    "Content-Type"  = "application/json"
}
$body = @{
    model = "llama3.2:1b"
    messages = @(
        @{ role = "user"; content = "Explain event streaming in 2 sentences." }
    )
    stream = $true
} | ConvertTo-Json

# Stream via curl.exe or Invoke-WebRequest
curl.exe -N -X POST "http://localhost:8000/v1/chat/completions" -H "Authorization: Bearer gw_test_your_client_key_here" -H "Content-Type: application/json" -d $body
```

#### Protocol Details
- **Content-Type**: `text/event-stream`
- **Cache-Control**: `no-cache`
- **Cache Policy**: `X-Cache: BYPASS` (streaming responses are neither read from nor stored in Redis cache).
- **Chunk Format**: `data: {"id": "...", "object": "chat.completion.chunk", "created": ..., "model": "...", "choices": [{"index": 0, "delta": {"content": "..."}, "finish_reason": null}]}`
- **Terminal Event**: `data: [DONE]`
- **Pre-Stream Failover**: Multi-provider failover will attempt configured fallback models if the primary provider fails *before* emitting chunk #0.
- **Mid-Stream Errors**: If an upstream error occurs *after* content has already been delivered, SafeRoute emits a sanitized `data: {"error": {...}}` event followed by `data: [DONE]`. Automatic cross-provider retry is strictly disallowed once content has been sent.
- **For complete architecture and client examples**, see [docs/phase_9_2_streaming.md](docs/phase_9_2_streaming.md).

---

### Unified Tool / Function Calling (Phase 9.3)

SafeRoute provides a unified, normalized tool/function-calling interface conforming to the OpenAI standard across Ollama and Mock providers.

> [!IMPORTANT]
> **Strict Security Execution Boundary**: SafeRoute **never** executes tool code, invokes external URLs, runs shell commands, or executes SQL queries. SafeRoute normalizes the model's tool-call request, returns it to the client application with `finish_reason: "tool_calls"`, and awaits client execution.

#### Request Example (Seattle Weather Tool)
```json
{
  "model": "llama3.2:1b",
  "messages": [
    {"role": "user", "content": "What's the weather in Seattle?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather for location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string"}
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

#### Normalized Response
```json
{
  "id": "chatcmpl-ollama-msg_123",
  "object": "chat.completion",
  "model": "llama3.2:1b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_123",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"location\":\"Seattle\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 85,
    "completion_tokens": 24,
    "total_tokens": 109,
    "is_mock_estimate": false,
    "usage_source": "provider_reported"
  }
}
```

#### Tool Result Follow-Up
Clients pass tool outputs back using `role: "tool"` and the associated `tool_call_id`:
```json
{
  "model": "llama3.2:1b",
  "messages": [
    {"role": "user", "content": "What's the weather in Seattle?"},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {"id": "call_123", "type": "function", "function": {"name": "get_weather", "arguments": "{\"location\":\"Seattle\"}"}}
      ]
    },
    {"role": "tool", "tool_call_id": "call_123", "content": "{\"temperature\": \"58F\", \"condition\": \"Rain\"}"}
  ]
}
```

For complete documentation, provider mapping tables, and streaming tool delta examples, see [docs/phase_9_3_tool_calling.md](docs/phase_9_3_tool_calling.md).

---

## Semantic Caching & Performance Benchmark (Phase 10)

SafeRoute provides a two-tiered, multi-tenant caching subsystem designed to accelerate inference, enforce client privacy, and ensure high reliability.

### Exact vs. Semantic Cache Architecture

1. **Tier 1 — Exact-Match Response Cache (`app/cache/redis_cache.py`)**:
   - SHA-256 canonical hashing across `namespace`, `client_id`, `provider`, `model`, messages array, `temperature`, `max_tokens`, `stream`, and `tools`.
   - Redis key pattern: `saferoute:{namespace}:exact:{client_id}:{sha256}`.
   - Microsecond Redis `GET` / `SET` with configurable TTL (`CACHE_TTL_SECONDS`).

2. **Tier 2 — Semantic Similarity Cache (`app/cache/semantic_cache.py`)**:
   - Evaluates dense vector representations of prompts using cosine similarity against candidate entries in Redis index sets (`saferoute:{namespace}:semantic_idx:{client_id}:{clean_model}`).
   - Default similarity threshold: `0.85` (`SEMANTIC_CACHE_THRESHOLD`).
   - Supports zero-dependency hash projection vectors (`DeterministicMockEmbeddingProvider`) and local CPU sentence transformers (`LocalSentenceTransformerEmbeddingProvider` with `all-MiniLM-L6-v2`).

### Safety Gates & Adversarial Protections

To eliminate incorrect response reuse and data leaks, the semantic cache enforces strict safety invariants:

- **Strict Multi-Tenant Isolation**: Candidate indices are keyed by `client_id`, and candidate payloads re-verify tenant ownership before evaluating similarity.
- **Adversarial Polarity Inversion Protection**: Queries differing by negation terms (`not`, `never`, `without`, `opposite`) are detected via invariant feature extraction and rejected (`polarity_inversion_mismatch`).
- **Numeric Entity Match**: Mathematical or quantitative queries with different numbers (e.g. `2+2` vs `2+3`) are rejected (`numeric_entity_mismatch`).
- **Length Disparity Protection**: Prevents short queries from matching long essay prompts sharing a common prefix (`query_length_disparity`).
- **System Instruction & Conversation Parity**: System prompt strings and SHA-256 hashes of prior conversation turns must match identically.
- **Temperature Determinism**: Deterministic requests (`temperature: 0.0`) cannot reuse outputs generated under non-zero temperatures.
- **Sensitive Context & PII Bypass**: Prompts matching regex patterns for API keys, bearer tokens, JWTs, credit cards, SSNs, and passwords automatically bypass the cache.
- **Personalized & Temporal Bypass**: Account-specific (`my order`, `my balance`) and live temporal questions (`current time`, `today's date`) bypass caching.
- **Streaming & Tool Bypass**: Requests with `stream=True` or tool declarations bypass semantic caching by design.
- **Fail-Open Resilience**: If Redis becomes unreachable (`ConnectionError`), the gateway logs a warning, returns header `X-Cache: ERROR`, and seamlessly proceeds with local Ollama inference.

### Local-Only Configuration & Setup

Add or adjust the following variables in `.env` to enable caching:

```bash
# Enable exact-match caching
CACHE_ENABLED=true
CACHE_TTL_SECONDS=3600
CACHE_NAMESPACE=v1
CACHE_FAILURE_POLICY=fail_open
REDIS_URL=redis://localhost:6379/0

# Enable semantic similarity caching
SEMANTIC_CACHE_ENABLED=true
SEMANTIC_CACHE_THRESHOLD=0.85
SEMANTIC_CACHE_TTL_SECONDS=86400
SEMANTIC_CACHE_EMBEDDING_PROVIDER=mock   # or "local" with sentence-transformers
```

### Benchmark Methodology & Latency Results

Benchmarks were executed locally against Ollama (`llama3.2:1b`) using 35 repeated queries across cold, warm uncached, exact-hit (25 trials), and semantic-hit (5 trials) stages.

| Stage / Metric | Latency / Value | Performance Impact |
| :--- | :---: | :--- |
| **Cold Request Latency** | **801.20 ms** | Initial Ollama connection + token generation |
| **Warm Uncached Latency (Median)** | **317.76 ms** | Baseline local generation across distinct queries |
| **Warm Uncached Latency (p95)** | **632.06 ms** | Peak uncached local generation |
| **Exact-Cache Hit Latency (Median)** | **11.05 ms** | **~29x speedup** over warm Ollama inference |
| **Exact-Cache Hit Latency (p95)** | **16.83 ms** | Peak exact-cache retrieval latency |
| **Semantic-Cache Hit Latency (Median)** | **11.89 ms** | **~27x speedup** with vector similarity evaluation |
| **Semantic-Cache Hit Latency (p95)** | **15.13 ms** | Peak semantic similarity retrieval latency |
| **Cache Hit Rate** | **85.71%** | 30 out of 35 requests avoided LLM inference |
| **Ollama Calls Avoided** | **30 calls** | 85.7% inference computation saved |
| **Errors & False Matches** | **0 (0.0%)** | Zero false-positive reuse, zero 5xx errors |

### Reproduction Commands

```powershell
# 1. Run all dedicated cache unit & integration tests (55 tests)
pytest tests/unit/test_cache.py tests/unit/test_semantic_cache.py tests/unit/test_semantic_cache_safety_audit.py tests/integration/test_caching.py -v

# 2. Run the complete project regression test suite (394 passed, 5 skipped)
pytest -q

# 3. Run the live end-to-end cache audit & performance benchmark against Ollama
python scripts/benchmark_cache_audit.py
```

---

## Docker Compose Deployment Foundation (Phase 11A)

Phase 11A introduces a containerized local deployment foundation orchestrated with Docker Compose. It enables running the SafeRoute gateway and an isolated Redis cache alongside your local development setup without conflicts, credential exposure, or SQLite file corruption.

```
+-----------------------------------------------------------------------------------+
| Host Machine (Windows / Linux / macOS)                                            |
|                                                                                   |
|  +-------------------------------+                                                |
|  | Local Ollama Server           | <===========================================+  |
|  | Port: 11434 (llama3.2:1b)     |                                             |  |
|  +-------------------------------+                                             |  |
|                                                                                |  |
|  +--------------------------------------------------------------------------+  |  |
|  | Docker Compose Stack                                                     |  |  |
|  |                                                                          |  |  |
|  |  +-------------------------+     Internal Network     +---------------+  |  |  |
|  |  | SafeRoute Gateway       | <----------------------> | Redis Cache   |  |  |  |
|  |  | (python:3.11-slim)      |                          | (redis:7)     |  |  |  |
|  |  | Non-root (UID 10001)    |                          | Port 6379     |  |  |  |
|  |  | Health: /health         |                          +---------------+  |  |  |
|  |  | Port: 8000 (or custom)  |                                  |          |  |  |
|  |  +-------------------------+                                  |          |  |  |
|  |               |                                               |          |  |  |
|  |               | SQLite WAL Mount                              | AOF Vol  |  |  |
|  |               v                                               v          |  |  |
|  |  +-------------------------+                          +---------------+  |  |  |
|  |  | Named Volume:           |                          | Named Volume: |  |  |  |
|  |  | saferoute-sqlite-data   |                          | saferoute-    |  |  |  |
|  |  | (/app/data)             |                          | redis-data    |  |  |  |
|  |  +-------------------------+                          +---------------+  |  |  |
|  +--------------------------------------------------------------------------+  |  |
|                  |                                                             |  |
|                  +------ http://host.docker.internal:11434 --------------------+  |
+-----------------------------------------------------------------------------------+
```

---

### Prerequisites and Architecture

1. **Docker Desktop**:
   - Windows 10/11 with WSL2 Linux backend, or Docker Engine 24+ on Linux/macOS.
   - Verify Docker is running: `docker --version` and `docker compose version`.
2. **Local Ollama on Host**:
   - SafeRoute inside Docker connects to your existing host Ollama server over `http://host.docker.internal:11434`.
   - Ensure Ollama is active on the host and the target model is pulled:
     ```bash
     ollama list
     # If needed: ollama pull llama3.2:1b
     ```
3. **No Cloud Dependencies**:
   - The deployment runs strictly offline using local Ollama and local mock infrastructure; no external paid APIs or accounts are required.

---

### Required Environment Variables & Configuration

Docker Compose reads configuration from an environment file (`.env.docker`). A documented template is provided at `.env.docker.example`.

#### 1. Create your deployment `.env`
```bash
cp .env.docker.example .env.docker
```

#### 2. Configure Key Variables
| Variable | Required? | Default / Example | Purpose |
| :--- | :---: | :--- | :--- |
| `APP_ENV` | Yes | `production` | Enables production validation rules and strict security checks. |
| `PORT` | Yes | `8000` | Gateway listening port mapped to the host (`8000:8000`). |
| `AUTH_SECRET` | Yes | *Generated via CLI* | Cryptographic secret for verifying HMAC-SHA256 client API keys. |
| `CLIENT_KEYS` | Yes | `[{"client_id": "...", "key_hash": "...", "enabled": true}]` | JSON list of authorized client hashes and IDs. |
| `ACTIVE_PROVIDER` | Yes | `ollama` | Active LLM inference provider (`ollama` or `mock`). |
| `OLLAMA_BASE_URL` | Yes | `http://host.docker.internal:11434` | Host Ollama bridge URL accessible from inside Docker. |
| `OLLAMA_MODEL` | Yes | `llama3.2:1b` | Default Ollama model. |
| `DATABASE_URL` | Yes | `sqlite:////app/data/saferoute.db` | Absolute path to SQLite DB inside the container's named volume. |
| `REDIS_URL` | Yes | `redis://redis:6379/0` | Connects to the adjacent Compose Redis service container. |
| `CACHE_ENABLED` | Yes | `true` | Enables Tier 1 Redis exact response caching. |
| `SEMANTIC_CACHE_ENABLED`| Yes | `true` | Enables Tier 2 semantic similarity caching. |
| `SEMANTIC_CACHE_EMBEDDING_PROVIDER` | Yes | `local` | `local` (sentence-transformers) is required in production. (`mock` is forbidden when `APP_ENV=production`). |

> [!CAUTION]
> **Secret Hygiene**: Never commit `.env.docker`, `.env`, or API key files to source control. They are strictly excluded by `.dockerignore` and `.gitignore`.

---

### Windows Development vs. Docker Compose Deployment

SafeRoute is engineered to support both native Windows development and Docker Compose deployment concurrently without interference:

| Feature | Windows Local Development | Docker Compose Deployment |
| :--- | :--- | :--- |
| **Execution** | Native Python venv (`.venv\Scripts\Activate.ps1`) | Containerized (`python:3.11-slim`, user `saferoute`) |
| **Startup** | `uvicorn app.main:app --reload --port 8000` | `docker compose up -d` |
| **Ollama URL** | `http://localhost:11434` | `http://host.docker.internal:11434` |
| **Redis URL** | `redis://localhost:6379/0` | `redis://redis:6379/0` |
| **Database Path** | `data/saferoute.db` (local NTFS path) | `/app/data/saferoute.db` (Linux named volume) |
| **Isolation** | Shared host environment | Fully containerized network & filesystem sandbox |

---

### Docker Compose Startup, Logs, and Shutdown

All commands should be executed from the repository root (`D:\SafeRoute LLM Gateway`):

```bash
# 1. Build the gateway Docker image
docker compose build

# 2. Start all services in the background (detached mode)
docker compose --env-file .env.docker up -d

# 3. Check service health and running status
docker compose ps

# 4. Follow streaming logs from the gateway service
docker compose logs -f gateway

# 5. Stop the containers gracefully (preserves database and cache volumes)
docker compose stop

# 6. Tear down containers and internal networks (preserves persistent volumes)
docker compose down

# 7. Complete teardown including volumes (CAUTION: wipes SQLite and Redis data)
docker compose down -v
```

---

### Host Ollama Connectivity (`host.docker.internal`)

Inside a Docker container, `localhost:11434` refers to the container's own loopback interface, not the host machine where Ollama is running.

SafeRoute solves this cleanly in `docker-compose.yml`:
```yaml
services:
  gateway:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
```

#### Verifying Connectivity from Container to Host Ollama:
```bash
docker compose exec gateway curl -s http://host.docker.internal:11434/api/tags
```
If this returns a JSON payload listing `llama3.2:1b`, your gateway container has verified line-of-sight to the host Ollama instance.

> [!NOTE]
> On Windows, Docker Desktop automatically bridges `host.docker.internal` to the host gateway. Ensure Windows Firewall permits incoming connections on port 11434 from the WSL2/vEthernet virtual adapter.

---

### Database Persistence, WAL Files, and Backup Considerations

SafeRoute uses SQLite in **Write-Ahead Logging (WAL)** mode. WAL requires POSIX-compliant atomic file locking for both the primary database (`saferoute.db`), write-ahead log (`saferoute.db-wal`), and shared-memory index (`saferoute.db-shm`).

#### Why Named Docker Volumes Instead of NTFS Bind Mounts?
Bind-mounting a Windows NTFS folder directly into a Linux container (`./data:/app/data`) causes POSIX lock translation overhead and can lead to `sqlite3.OperationalError: database is locked` during high-concurrency WAL checkpointing.

SafeRoute uses a **named Docker volume** (`saferoute-sqlite-data`):
```yaml
volumes:
  saferoute-sqlite-data:
    name: saferoute-sqlite-data
```
This volume resides entirely within the native Linux ext4 filesystem managed by Docker/WSL2, guaranteeing 100% compliant POSIX locking, zero WAL corruption, and instant crash recovery across container restarts.

#### Database Backup Procedure:
To safely back up the active SQLite database while the container is running without interrupting traffic, use the SQLite online backup API:
```bash
# 1. Create a safe, checkpointed online snapshot inside the container
docker compose exec gateway sqlite3 /app/data/saferoute.db ".backup '/app/data/backup_snapshot.db'"

# 2. Copy the snapshot to your host backups folder
docker cp saferoute-gateway-1:/app/data/backup_snapshot.db ./data/backup_$(date +%Y%m%d).db

# 3. Remove the temporary snapshot inside the volume
docker compose exec gateway rm /app/data/backup_snapshot.db
```

---

### Health Probes & Readiness Separation (`/health` vs. `/ready`)

SafeRoute strictly decouples **process liveness** from **dependency readiness**:

1. **Liveness Check (`GET /health`)**:
   - Used by the Dockerfile `HEALTHCHECK` instruction and orchestrator restart policies.
   - Verifies the FastAPI event loop is active and answering HTTP requests.
   - Returns: `{"status": "ok"}` (HTTP 200).
   - Will NOT restart a healthy gateway if an external dependency (such as Ollama) experiences transient slowness.

2. **Readiness Check (`GET /ready`)**:
   - Used by load balancers, deployment gates, and traffic routers before forwarding client requests.
   - Deeply probes every required operational dependency:
     - **Database**: Executes `SELECT 1` on the persistent SQLite session.
     - **Redis**: Sends an atomic `PING` to the Redis cache cluster.
     - **Active Provider**: Validates HTTP connectivity to the configured provider (e.g. Ollama `/api/tags`).
   - Returns: HTTP 200 with detailed status if all are healthy, or HTTP 503 if any dependency is degraded.

---

### Security Architecture & Container Hardening

- **Non-Root Execution**: The gateway runs under an unprivileged system user `saferoute` (UID `10001`, GID `10001`). Even in the unlikely event of an application exploit, the attacker possesses zero root privileges inside or outside the container.
- **Minimal Attack Surface**: Built upon `python:3.11-slim`, purging build dependencies (`gcc`, `g++`) from the final runtime image and keeping only `curl` for container health monitoring.
- **Strict `.dockerignore`**: Excludes `.env*`, `.dev_api_key.txt`, virtual environments (`.venv`), Git metadata (`.git`), SQLite database files (`data/*.db`), and bytecode (`__pycache__`) from image build context.
- **Startup Secret Masking**: The gateway validates all environment variables and cryptographic key verifiers at startup without ever logging raw keys, passwords, or tokens.

---

### Troubleshooting & Diagnostics

#### 1. Port 8000 Conflict
If your host already has a service running on port 8000 (e.g. local uvicorn dev server):
Edit `docker-compose.yml` or set in `.env.docker`:
```yaml
ports:
  - "8001:8000"
```
The gateway will be accessible at `http://localhost:8001`.

#### 2. Host Ollama Connection Refused
If the gateway logs `httpx.ConnectError: [Errno 111] Connection refused`:
- Confirm Ollama is running on the host: `curl http://localhost:11434/api/tags`.
- If on Windows, ensure Ollama is bound to all interfaces or the WSL network. Set environment variable `OLLAMA_HOST=0.0.0.0:11434` in Windows and restart Ollama.

#### 3. Mock Embedding Provider in Production Error
If startup fails with `ValidationError: Mock embedding provider 'mock' is strictly forbidden in production`:
- In `production` mode (`APP_ENV=production`), SafeRoute requires real embeddings.
- Ensure `SEMANTIC_CACHE_EMBEDDING_PROVIDER=local` is set in your `.env.docker` file.

#### 4. Inspecting Database Records Inside the Volume
```bash
docker compose exec gateway python -c "
import sqlite3
con = sqlite3.connect('/app/data/saferoute.db')
print('Total requests:', con.execute('SELECT COUNT(*) FROM requests').fetchone()[0])
"
```

---

## Prometheus Metrics & Observability (Phase 11B)

SafeRoute provides a first-class, privacy-conscious Prometheus metrics subsystem implemented with the official `prometheus-client` Python SDK. The observability pipeline measures gateway throughput, end-to-end request latency, provider failover latency, error counts, cache utilization (exact and semantic), token usage breakdown, active streaming concurrency, guardrail blocks, and rate limit rejections.

All metrics are instrumented with **strictly bounded label cardinalities** to safeguard Prometheus timeseries databases against cardinality explosion. SafeRoute never uses user IDs, client identifiers, raw user prompts, unauthenticated endpoints, arbitrary input model names, API keys, or secrets as metric labels.

### Overview & Metric Architecture

The metrics system operates through four coordinated layers:
1. **HTTP Lifecycle Middleware (`app/main.py`)**: Intercepts all inbound requests, recording total requests (`saferoute_requests_total`) and high-resolution gateway duration histograms (`saferoute_request_duration_seconds`) across standardized route patterns (`normalize_route`) and HTTP status codes.
2. **Provider Failover Engine (`app/providers/failover.py`)**: Instruments upstream model execution latencies (`saferoute_provider_duration_seconds`) and provider-level errors/timeouts (`saferoute_provider_errors_total`) with bounded provider identities (`normalize_provider`).
3. **Route & Inference Handlers (`app/api/routes.py`)**: Tracks fine-grained application events, including cache hits/misses (`saferoute_cache_operations_total`), token consumption provenance (`saferoute_tokens_total`), rate limit exceedances (`saferoute_rate_limit_exceeded_total`), guardrail rejections (`saferoute_guardrail_blocks_total`), and currently open streaming connections (`saferoute_streaming_requests_active`).
4. **Resilient Fail-Safe Isolation (`app/metrics.py`)**: Metric updates are encapsulated in non-throwing wrappers. Any metric recording error logs a warning and will never interrupt, degrade, or fail an active LLM inference request.

---

### Exposed Metrics Catalog

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `saferoute_requests_total` | Counter | `route`, `status`, `provider` | Total inbound HTTP requests processed by the gateway. |
| `saferoute_request_duration_seconds` | Histogram | `route`, `status` | End-to-end HTTP request duration in seconds (buckets: 5ms to 60s). |
| `saferoute_provider_duration_seconds` | Histogram | `provider`, `model` | Upstream provider execution latency in seconds (buckets: 10ms to 120s). |
| `saferoute_provider_errors_total` | Counter | `provider`, `error_type` | Total errors encountered when calling upstream providers (`timeout`, `connection`, `http_error`, `runtime`). |
| `saferoute_cache_operations_total` | Counter | `cache_type`, `event` | Total cache operations partitioned by cache type (`exact`, `semantic`) and event (`hit`, `miss`, `bypass`, `error`). |
| `saferoute_tokens_total` | Counter | `type`, `provider`, `model`, `source` | Total input and output tokens processed. `source` indicates provenance: `"provider"` (upstream reported) or `"estimated"` (fallback tokenizer). |
| `saferoute_streaming_requests_active` | Gauge | `provider` | Number of currently active, open streaming responses. |
| `saferoute_rate_limit_exceeded_total` | Counter | `route` | Inbound requests rejected due to rate limiting (HTTP 429). |
| `saferoute_guardrail_blocks_total` | Counter | `stage`, `rule_type` | Inbound or outbound requests rejected by guardrail policies (`stage`: `input` or `output`). |

#### Bounded Cardinality Label Constraints
- `route`: Normalized to safe, bounded endpoints: `"/v1/chat/completions"`, `"/v1/usage/summary"`, `"/v1/usage/export"`, `"/health"`, `"/ready"`, `"/metrics"`, or `"other"`. Raw, client-crafted URLs are never exposed.
- `provider`: Bounded to known registered providers: `"ollama"`, `"mock"`, `"gateway"`, or `"unknown"`.
- `model`: Normalized against the gateway's verified model catalog (`"llama3.2:1b"`, `"llama3.2:3b"`, `"mock-model"`, etc.). Unrecognized user-submitted model strings map to `"other"`.
- `status`: Standard HTTP status string (e.g. `"200"`, `"400"`, `"401"`, `"429"`, `"500"`, `"504"`).

---

### Configuration & Security Options

Metrics exposure is controlled via environment variables:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `METRICS_ENABLED` | bool | `true` | Enables or disables the `/metrics` endpoint. When set to `false`, the route returns HTTP 404. |
| `METRICS_PATH` | str | `"/metrics"` | Path where Prometheus text exposition is served. |
| `METRICS_REQUIRE_AUTH` | bool | `false` | When `true`, accessing `/metrics` requires authentication via Bearer token. |
| `METRICS_AUTH_TOKEN` | str | `""` | Dedicated secret token for Prometheus scrapers (`Authorization: Bearer <token>`). If unset but auth is required, valid client API keys are accepted. |

#### Security Best Practices
- **Internal / VPC Scrapers (Default)**: In internal containerized networks (such as Docker Compose or Kubernetes overlay networks), keep `METRICS_REQUIRE_AUTH=false`. The port or `/metrics` route should not be exposed to the public internet.
- **Dedicated Scraper Authentication**: For multi-tenant or exposed ingress setups, configure:
  ```env
  METRICS_REQUIRE_AUTH=true
  METRICS_AUTH_TOKEN=your-high-entropy-metrics-secret
  ```
  Prometheus scrapers then authenticate using `bearer_token: your-high-entropy-metrics-secret`.

---

### Sample Prometheus Exposition Output

```text
# HELP saferoute_requests_total Total HTTP requests processed by SafeRoute Gateway.
# TYPE saferoute_requests_total counter
saferoute_requests_total{provider="ollama",route="/v1/chat/completions",status="200"} 42.0
saferoute_requests_total{provider="gateway",route="/health",status="200"} 120.0
saferoute_requests_total{provider="gateway",route="/v1/chat/completions",status="401"} 3.0

# HELP saferoute_request_duration_seconds HTTP request latency histogram.
# TYPE saferoute_request_duration_seconds histogram
saferoute_request_duration_seconds_bucket{le="0.005",route="/v1/chat/completions",status="200"} 0.0
saferoute_request_duration_seconds_bucket{le="0.05",route="/v1/chat/completions",status="200"} 14.0
saferoute_request_duration_seconds_bucket{le="0.5",route="/v1/chat/completions",status="200"} 38.0
saferoute_request_duration_seconds_bucket{le="2.5",route="/v1/chat/completions",status="200"} 42.0
saferoute_request_duration_seconds_count{route="/v1/chat/completions",status="200"} 42.0
saferoute_request_duration_seconds_sum{route="/v1/chat/completions",status="200"} 18.234

# HELP saferoute_provider_duration_seconds Latency of calls made to upstream providers.
# TYPE saferoute_provider_duration_seconds histogram
saferoute_provider_duration_seconds_bucket{le="0.1",model="llama3.2:1b",provider="ollama"} 5.0
saferoute_provider_duration_seconds_bucket{le="1.0",model="llama3.2:1b",provider="ollama"} 39.0
saferoute_provider_duration_seconds_count{model="llama3.2:1b",provider="ollama"} 40.0

# HELP saferoute_cache_operations_total Total cache operations by type and event.
# TYPE saferoute_cache_operations_total counter
saferoute_cache_operations_total{cache_type="exact",event="hit"} 18.0
saferoute_cache_operations_total{cache_type="exact",event="miss"} 24.0
saferoute_cache_operations_total{cache_type="semantic",event="hit"} 6.0
saferoute_cache_operations_total{cache_type="semantic",event="miss"} 18.0
saferoute_cache_operations_total{cache_type="semantic",event="bypass"} 8.0

# HELP saferoute_tokens_total Total tokens processed by type, provider, model, and provenance source.
# TYPE saferoute_tokens_total counter
saferoute_tokens_total{model="llama3.2:1b",provider="ollama",source="provider",type="prompt"} 894.0
saferoute_tokens_total{model="llama3.2:1b",provider="ollama",source="provider",type="completion"} 2450.0

# HELP saferoute_streaming_requests_active Currently active streaming requests.
# TYPE saferoute_streaming_requests_active gauge
saferoute_streaming_requests_active{provider="ollama"} 0.0
```

---

### Zero Double-Counting & Provenance Handling

1. **Zero Double-Counting on Cache Hits**:
   - When a request achieves an exact or semantic cache hit, SafeRoute serves the response immediately from Redis or memory without calling the upstream provider.
   - `saferoute_tokens_total` is **not** incremented on cache hits. This preserves token counter purity, ensuring token metrics accurately reflect true computational load and billing impact on upstream providers.
   - Cache hits increment `saferoute_cache_operations_total{cache_type="exact|semantic", event="hit"}`.

2. **Accurate Streaming Measurement**:
   - Streaming requests increment `saferoute_streaming_requests_active{provider=...}` when the SSE generator opens and decrement the gauge in a `finally` block when the stream terminates or disconnects.
   - Streamed requests do not double-increment request counters; the outer middleware records exactly one request completion when the final streaming chunk is sent.

3. **Token Count Provenance**:
   - `source="provider"`: High-confidence token counts returned directly by the upstream provider (e.g. Ollama `prompt_eval_count` and `eval_count`).
   - `source="estimated"`: Heuristic token counts computed using whitespace/character estimation when the upstream provider does not report usage.

---

### Prometheus & Docker Compose Scraping Configuration

To scrape SafeRoute metrics with Prometheus, add the gateway service to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'saferoute-gateway'
    scrape_interval: 15s
    scrape_timeout: 5s
    metrics_path: '/metrics'
    # If METRICS_REQUIRE_AUTH=true, configure bearer_token:
    # bearer_token: 'your-metrics-token'
    static_configs:
      - targets: ['gateway:8000']
        labels:
          environment: 'production'
          service: 'llm-gateway'
```

---

## Streaming Cache Replay (Phase 11C)

Phase 11C implements safe, high-performance replay of compatible cached responses for streaming chat completions (`stream=true`) without breaking existing non-streaming cache semantics, SSE protocol invariants, client isolation, or Prometheus metrics.

### Architecture & Compatibility Guarantees
- **Unified Cache Storage**: Completed responses cached by either non-streaming (`stream=false`) or streaming (`stream=true`) requests are stored in the canonical `ChatCompletionResponse` schema.
- **Cross-Replay Compatibility**:
  - A completion generated via standard non-streaming request can be replayed as a compliant Server-Sent Events (`text/event-stream`) stream to a streaming caller.
  - A completion generated via streaming request can be served to a subsequent non-streaming caller.
- **Cache Identity**: `build_cache_key()` excludes the transient transport indicator `stream` while deterministically hashing all response-affecting parameters: `client_id`, `provider`, `model`, `messages`, `temperature`, `max_completion_tokens`, `system_fingerprint`, and tool configurations.

### Safe Cache Eligibility Rules
1. **Completion Integrity**: Responses are committed to cache **only after clean, terminal completion** (`stream_status == "completed"`).
2. **Never Cache Partial Data**: Any stream aborted by client disconnect (`asyncio.CancelledError`), upstream timeout, socket drop, or provider error is immediately marked `stream_status != "completed"` and is **never** stored.
3. **Failover & Safety Flags**: Responses involving provider failover or flagged safety categories are marked `BYPASS` and never cached, preventing cross-model pollution.
4. **Output Safety Guardrails**: Cached responses undergo output rule inspection and safety classification prior to replay. If blocked, the stale entry is immediately evicted with an eviction metric recorded, and an HTTP 502 error is returned.

### OpenAI SSE Replay Protocol
Replay adheres strictly to standard OpenAI chunk sequencing:
1. **Initial Header Chunk**: Emits role `assistant` with empty content delta `""`.
2. **Body Chunks**: Replays content in discrete SSE chunks:
   ```text
   data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":...,"model":"...","choices":[{"index":0,"delta":{"content":"..."},"finish_reason":null}]}
   ```
3. **Tool Call Serialization**: If the response contains function calls, tool call arguments and metadata are structured in compliant `delta.tool_calls` chunks.
4. **Terminal Chunk**: Emits the final chunk with the true `finish_reason` ("stop", "tool_calls", etc.) and genuine usage metadata.
5. **Termination Marker**: Emits terminal `data: [DONE]\n\n`.

### Zero Double-Counting & Metrics Accuracy
- **Zero Upstream Inferences**: Cache hits never call local Ollama or cloud providers (`0` upstream requests/tokens).
- **Zero Token Double-Counting**: Replayed streaming cache hits record `usage_source="cache_hit"` in SQLite and increment `saferoute_cache_operations_total{cache_type="exact",event="hit"}` without double-counting provider tokens in `saferoute_tokens_total`.
- **Active Streams Gauge**: `saferoute_streaming_requests_active` increments when the replay begins and decrements back to baseline when the stream finishes or client disconnects.

### Failure, Disconnect & Adversarial Protections
- **Redis Outage Fail-Open**: If Redis fails, requests fall back to live provider execution with `X-Cache: ERROR`.
- **Malformed Cache Data**: If corrupted JSON is retrieved from cache, the entry is automatically purged and the request falls back safely to the upstream provider without raising 500.
- **Client Isolation**: Client Alice can never access or replay responses generated by Client Bob, even with identical prompts.

### Configuration & Live Validation
Streaming cache replay is controlled via `STREAMING_CACHE_REPLAY_ENABLED`:
```env
CACHE_ENABLED=true
STREAMING_ENABLED=true
STREAMING_CACHE_REPLAY_ENABLED=true
```
When validated against local Ollama (`llama3.2:1b`), cache replay delivered **143.7x lower latency** (46ms vs 6,622ms) with identical token-by-token output.

---

## Operational Hardening & Production Readiness (Phase 12)

Phase 12 elevates SafeRoute from a feature-complete gateway prototype to a hardened, resilient, production-ready system.

### Configuration Validation & Startup Safety (Phase 12A)
- **Production Auth Invariant**: Setting `APP_ENV=production` strictly forbids disabling `AUTH_ENABLED`. Attempts to boot an unauthenticated gateway in production fail fast at startup with a descriptive error.
- **HMAC Secret Strength**: Rejects weak or empty `AUTH_SECRET` configurations (< 16 characters) to eliminate trivial brute-force vulnerability.
- **Connection Scheme Validation**: `DATABASE_URL` is validated against supported relational drivers (`sqlite:///`, `postgresql://`, `mysql://`); `OLLAMA_BASE_URL` requires valid `http://` or `https://` schemas and rejects missing hostnames.
- **Metrics Scraping Guard**: Enforces that enabling `METRICS_REQUIRE_AUTH=true` requires either a dedicated `METRICS_AUTH_TOKEN` or a valid gateway `AUTH_SECRET`.
- **CORS Allowed Origins Parsing**: Robust parser supporting JSON arrays, comma-delimited strings, and multi-origin lists with safe wildcard fallback in development.

### Failure Recovery, Readiness & SQLite Hardening (Phase 12B)
- **Readiness vs. Health Separation**:
  - `/health` is a lightweight liveness probe verifying HTTP availability (returns 200).
  - `/ready` conducts deep dependency verification across active upstream providers, relational database connectivity, and Redis cache/rate-limiter availability.
- **Failure Policy Alignment**: The readiness endpoint correctly reads `rate_limit_failure_policy` (fixing earlier typos) and respects `fail_closed` (HTTP 503) vs. `fail_open` (HTTP 200) policies when Redis is offline.
- **SQLite Concurrency & Busy Timeout**:
  - Attached `PRAGMA busy_timeout=15000` via SQLAlchemy `Engine.connect` event listener to ensure every SQLite connection waits up to 15 seconds before raising locked errors.
  - Configured `connect_args={"check_same_thread": False, "timeout": 15.0}`.
  - Preserved Write-Ahead Logging (`PRAGMA journal_mode=WAL`), foreign key cascades, and atomic ACID transactions under heavy multi-threaded write concurrency.
- **Docker Compose Passthrough**: Explicit mapping and safe defaults for `METRICS_ENABLED`, `STREAMING_CACHE_REPLAY_ENABLED`, `STREAMING_ENABLED`, and `METRICS_REQUIRE_AUTH`.

### CORS & Defensive HTTP Security Headers (Phase 12C)
- **CORSMiddleware**: Seamless cross-origin request support for browser integrations. Restricts wildcard credentials (`allow_credentials=False` when `*` is configured) complying with W3C browser security standards.
- **Defensive Headers**: Every response—including successful completions, error envelopes, and streaming SSE responses—is hardened with:
  - `X-Content-Type-Options: nosniff` (prevents MIME type sniffing)
  - `X-Frame-Options: DENY` (prevents clickjacking and unauthorized embedding)
- **Tenant Isolation**: Strict isolation guarantees that Client Alice cannot inspect, scrape, or export Client Bob's usage statistics or cached completions.

### Controlled Load Testing & Benchmarking (Phase 12D)
A standalone load testing utility is available in [`scripts/benchmark_load.py`](scripts/benchmark_load.py):
```bash
python scripts/benchmark_load.py --requests 50 --concurrency 10 --suite mock_matrix
```
Supports configurable request counts, concurrency levels (1, 10, 20), streaming vs. non-streaming execution, TTFT measurement, and produces machine-readable JSON results and Markdown summary tables.

---

## Running Tests

SafeRoute maintains an extensive, completely offline regression suite covering authentication, database persistence, streaming, caching, provider failover, Prometheus metrics, and streaming cache replay.

### Run All Tests
```bash
pytest
```
*Current verified test baseline: **409 passed, 3 skipped, 0 failures (412 total)**. (The 3 skipped tests are live opt-in cloud infrastructure checks in `tests/integration/test_live_infrastructure_opt_in.py`).*

### Targeted Test Suites
```bash
# Authentication & Management APIs
pytest tests/unit/test_auth.py tests/unit/test_management_api.py -v

# Core routing, failover, Ollama provider, and config
pytest tests/unit/test_config.py tests/unit/test_ollama_provider.py tests/unit/test_failover.py -v

# Production readiness, CORS, defensive headers, and SQLite concurrency
pytest tests/integration/test_production_readiness.py -v

# System reliability and failure recovery audit
pytest tests/integration/test_reliability_audit.py -v

# Streaming and streaming-cache replay suites
pytest tests/unit/test_streaming.py tests/unit/test_streaming_cache.py tests/integration/test_streaming_cache.py -v

# Safety classification and guardrails
pytest tests/unit/test_guardrails.py tests/unit/test_safety_classification.py -v
```

---

## Performance Benchmarking (Verified & Strictly Separated)

SafeRoute evaluates performance with strictly separated workloads to avoid blending cached response times with real upstream inference.

### Verified Benchmark Results

| Benchmark Workload | Provider / Model | Concurrency & Reqs | Throughput | Latency p50 | Latency p95 | Cache Hit Rate | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Uncached Local Inference** | `ollama / llama3.2:1b` | c=1, n=3 unique | **1.69 req/s** | **523.32 ms** | **812.29 ms** | **0.0%** (True Miss) | 100% Success |
| **Exact-Cache Warm Hit** | `ollama / llama3.2:1b` | c=5, n=20 warm | **37.23 req/s** | **104.34 ms** | **210.04 ms** | **100.0%** (Exact Hit) | 100% Success (~5.0x speedup) |
| **Streaming Local Inference** | `ollama / llama3.2:1b` | c=1, n=3 unique | **0.98 req/s** | **1013.57 ms** (TTFT: 372ms) | **1025.31 ms** | **0.0%** (True Miss) | 100% Success |
| **High-Load Mock Double** | `mock / mock-model` | c=10, n=50 | **48.36 req/s** | **195.64 ms** | **270.35 ms** | N/A | 100% Success |
| **Controlled Error Rejection** | Invalid model payload | c=1, n=10 | N/A | **1.95 ms** | **2.50 ms** | N/A | 100% Rejection (HTTP 400) |

To reproduce these verified benchmarks locally:
```bash
python scripts/benchmark_hardening_verified.py
```

---

## Administration & Telemetry Console (Frontend)

SafeRoute includes a dark-themed, enterprise-grade React / TypeScript / Vite administration console located in `frontend/`.

### Architecture & Design System
- **Stack**: React 18, TypeScript, Tailwind CSS, Lucide Icons, Recharts, Vite.
- **Color Palette**: Enterprise slate dark mode (`#11162B` canvas, `#151B34` sidebar, `#202A49` card surfaces, `#354364` borders).
- **Typography**: Google Fonts (`Inter` for interface elements, `JetBrains Mono` for code, hashes, and metrics).
- **Navigation**: Collapsible responsive sidebar with mobile drawer (< 768px).

### 11 Implemented & Audited Routes
1. **Overview (`/`)**: High-level telemetry, live latency percentiles (P50/P90/P99), request volume AreaChart, and recent request feed.
2. **Request Explorer (`/requests`)**: Real-time request log with client ID, route, model, latency, tokens, cost, and slide-over inspector detailing audit compliance (zero prompt retention).
3. **LLM Playground (`/playground`)**: Interactive completion console with model selector (`llama3.2:1b`, `qwen2.5-coder`, `mock-model`), system prompt, temperature, and token limit controls.
4. **Providers & Routing (`/providers`)**: Upstream provider health, locally pulled Ollama models, capability matrix, and failover status.
5. **Cache Monitor (`/cache`)**: Exact cache hit rate, avoided model latency, Redis broker status, and semantic cache similarity threshold.
6. **Usage & Costs (`/usage`)**: Token consumption accounting, localized cost estimation ($0.0000 for local Ollama), and direct CSV export.
7. **Database Explorer (`/database`)**: Read-only SQLite viewer showing WAL journal mode, table schemas (`clients`, `request_records`, `usage_records`), and row counts.
8. **Errors & Reliability (`/reliability`)**: Standardized error taxonomy breakdown, failover event logs, and status distribution.
9. **System Health (`/health`)**: 4-column service health grid (Gateway, SQLite, Redis, Ollama) and monospace Prometheus raw telemetry viewer with live search filtering.
10. **Security & Guardrails (`/security`)**: Active PII masking status (SSN, credit card, API key, email, phone), prompt injection rules, and HMAC-SHA256 bearer key indicators.
11. **Configuration (`/config`)**: Sanitized runtime configuration viewer.

---

## Windows Quickstart & Verification Commands

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ and npm
- Redis running on `127.0.0.1:6379`
- Ollama running on `127.0.0.1:11434` with model `llama3.2:1b` (`ollama pull llama3.2:1b`)

### 2. Start the Backend Gateway
```powershell
# In repository root D:\SafeRoute LLM Gateway
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 3. Start the Frontend Dashboard
```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

### 4. Verify Health & Telemetry
```powershell
# Check liveness
curl http://127.0.0.1:8000/health

# Check deep readiness
curl http://127.0.0.1:8000/ready

# Check Prometheus metrics
curl http://127.0.0.1:8000/metrics
```

### 5. Send an Authenticated Request
```powershell
$DEV_KEY = Get-Content .dev_api_key.txt -Raw -ErrorAction SilentlyContinue

curl -X POST http://127.0.0.1:8000/v1/chat/completions `
  -H "Authorization: Bearer $DEV_KEY" `
  -H "Content-Type: application/json" `
  -d '{\"model\": \"llama3.2:1b\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello, SafeRoute!\"}], \"max_completion_tokens\": 50}'
```

---

## Portfolio Release Summary & Architecture

### System Architecture Overview
```
                     +----------------------------------------+
                     |         Client Application / Agent      |
                     +----------------------------------------+
                                         |
                                         | HTTP / SSE (Bearer Token)
                                         v
                     +----------------------------------------+
                     |         FastAPI Gateway Boundary       |
                     |  - CORS & Defensive HTTP Headers       |
                     |  - Request Tracking & Request-ID       |
                     |  - Payload Size Limits (< 1 MB)        |
                     +----------------------------------------+
                                         |
                                         v
                     +----------------------------------------+
                     |     HMAC-SHA256 Auth & Rate Limiter    |
                     |  - Constant-time Verifier Check        |
                     |  - Redis Atomic Fixed-Window Limiter   |
                     +----------------------------------------+
                                         |
                     +-------------------+--------------------+
                     |                                        |
                     v                                        v
     +-------------------------------+        +-------------------------------+
     |     Input Safety Guardrails   |        |   Exact / Semantic Cache      |
     |  - Regex / Blocklist Rules    |        |  - Redis SHA-256 Key Match    |
     |  - Prompt Injection Classifier|        |  - Semantic Similarity Cosine |
     +-------------------------------+        +-------------------------------+
                     |                                        |
                     | (Cache Miss / Ineligible)              | (Cache Hit)
                     v                                        |
     +-------------------------------+                        |
     |   Provider Routing & Failover |                        |
     |  - Local Ollama Engine        |                        |
     |  - Failover to Healthy Models |                        |
     |  - Deterministic Mock Provider|                        |
     +-------------------------------+                        |
                     |                                        |
                     +-------------------+--------------------+
                                         |
                                         v
                     +----------------------------------------+
                     |    Output Guardrails & Redaction       |
                     |  - PII Masking & Toxicity Inspection   |
                     |  - Cache Population (Safe Responses)   |
                     +----------------------------------------+
                                         |
                     +-------------------+--------------------+
                     |                                        |
                     v                                        v
     +-------------------------------+        +-------------------------------+
     |  SQLite Transactional Storage |        |  Prometheus Observability     |
     |  - Request Records & Tokens   |        |  - Request Counts & Latencies |
     |  - Versioned Cost Accounting  |        |  - Active Streams Gauge       |
     |  - WAL Mode & Busy Timeout    |        |  - Token Throughput Metrics   |
     +-------------------------------+        +-------------------------------+
```

### Verified Performance Benchmark Matrix (Local Ollama & Redis)
*Extracted from real executions in `docs/BENCHMARKS.md` and `docs/evidence/benchmarks_verified.txt`:*

| Workload | Mode | Concurrency | Requests | Success / Fail | Throughput | p50 Latency | p95 Latency | p99 Latency | Cache Hit Rate | TTFT p50 |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Uncached Local Ollama (`llama3.2:1b`)** | Non-Streaming (Unique) | 1 | 50 | 50 / 0 | **1.75 req/s** | **560.48 ms** | 680.66 ms | 713.52 ms | **0.0%** (`MISS`) | N/A |
| **Uncached Local Ollama (`llama3.2:1b`)** | Non-Streaming (Unique) | 5 | 50 | 50 / 0 | **1.89 req/s** | **2591.52 ms** | 2901.12 ms | 2943.58 ms | **0.0%** (`MISS`) | N/A |
| **Exact-Cache Warm Hit (`llama3.2:1b`)** | Non-Streaming (Cache Hit) | 1 | 50 | 50 / 0 | **68.25 req/s** | **13.29 ms** | 22.78 ms | 30.12 ms | **100.0%** (`HIT`) | N/A |
| **Exact-Cache Warm Hit (`llama3.2:1b`)** | Non-Streaming (Cache Hit) | 5 | 50 | 50 / 0 | **124.41 req/s** | **37.44 ms** | 51.53 ms | 83.87 ms | **100.0%** (`HIT`) | N/A |
| **Streaming Local Ollama (`llama3.2:1b`)** | Streaming (Unique) | 1 | 50 | 50 / 0 | **0.98 req/s** | **1004.13 ms** | 1128.82 ms | 1229.21 ms | **0.0%** (`MISS`) | **375.05 ms** |
| **Mock Provider Uncached (`mock-model`)** | Non-Streaming (Unique) | 5 | 50 | 50 / 0 | **113.38 req/s** | **36.03 ms** | 64.61 ms | 102.96 ms | **0.0%** (`MISS`) | N/A |
| **Mock Provider Warm-Cache (`mock-model`)** | Non-Streaming (Cache Hit) | 5 | 50 | 50 / 0 | **118.74 req/s** | **30.89 ms** | 65.05 ms | 140.42 ms | **100.0%** (`HIT`) | N/A |
| **Invalid Model Safe Rejection** | Error Policy (HTTP 400) | 1 | 50 | 50 / 0 | **112.78 req/s** | **7.66 ms** | 14.31 ms | 21.90 ms | **0.0%** | N/A |

*Controlled Acceleration: Exact-cache warm hits achieved a matched-concurrency p50 latency of **13.29 ms** vs **560.48 ms** uncached at c=1 (a **42.17x latency reduction**), and **37.44 ms** vs **2591.52 ms** at c=5 (a **69.22x latency reduction**). Streaming provided initial token feedback in **375.05 ms** (a **62.6% reduction in user-perceived waiting time**).*

### Test Suite Verification & Code Coverage
- **Total Tests:** **418 passed tests** (409 core unit/integration + 9 automated security tests).
- **Code Coverage:** **83% overall coverage** across 5,375 statements (verified in `docs/evidence/backend_coverage.txt`).
- **Frontend Code Splitting:** Route-level `React.lazy` reduced initial production bundle from **840 kB** down to **318 kB** (-62%).
- **Dependency Audit:** Clean `pip-audit --local` (0 known vulnerabilities).
- **Docker Verification:** Verified non-root runtime container execution (`uid=10001(saferoute)`), passing `/health`, `/ready`, and `/metrics` probes.

### Engineering Highlights & Resume Summary
- **OpenAI Compatibility**: Seamless drop-in replacement for OpenAI client libraries, supporting completions, tool/function calling, and real-time SSE streaming.
- **Zero Cloud Costs**: Fully self-contained local development using offline Ollama (`llama3.2:1b`) and deterministic provider mocks.
- **Multi-Tenant Security**: Cryptographic HMAC-SHA256 authentication, constant-time key comparisons, tenant-isolated cache namespaces, and defensive HTTP security headers.
- **Resilient Reliability**: Multi-provider fallback cascades, configurable fail-open/fail-closed policies, ReDoS-protected regex engines, and graceful degradation during cache or database outages.
- **Enterprise Observability**: Zero-leakage structured logging, Prometheus instrumentation (`/metrics`), custom React observability UI, and exportable SQLite token accounting.

---

## Known Limitations & Production Architecture

### Known Limitations
- **Fixed-Window Rate Limiting**: The current rate limiter uses an atomic fixed-window Lua script. While highly performant with minimal Redis memory overhead, it permits up to 2x burst traffic at the boundary between two adjacent windows.
- **Single-Node SQLite Concurrency**: SQLite with WAL mode and `PRAGMA busy_timeout=15000` provides robust zero-dependency concurrency for single-node deployments and local demos. For horizontally scaled multi-node clusters requiring high concurrent writes (>200 write req/s), PostgreSQL is recommended. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete migration blueprint.
- **Heuristic Guardrails**: Input/output filters use deterministic regular expressions and token heuristics. They provide defense-in-depth against common prompt injections and PII leakage, but do not provide a formal mathematical guarantee against novel adversarial token sequences.
- **Semantic Caching Conservatism**: Semantic vector caching operates with a conservative cosine threshold (`0.85`) to avoid false-positive cache collisions across differing intents. Small query variations may miss the semantic cache by design.
- **Small Local Model Benchmarks**: Inference measurements reflect a local AMD64 workstation running `llama3.2:1b` (`Q8_0` quantization) on CPU/GPU. Production latency with enterprise cloud models or dedicated inference clusters will differ based on upstream hardware.
- **Observability Scope**: Observability is delivered via native Prometheus exposition (`GET /metrics`) and a custom, real-time React dashboard. Standalone Grafana dashboard templates are not bundled.
- **Container Build Verification**: Docker packaging is verified with an unprivileged non-root user (`uid=10001`), persistent data volumes, and container health probes.

### Architectural Documentation
For in-depth design rationale, trade-offs, and failure policies, consult:
- [Technical Architecture & Design Decisions](docs/ARCHITECTURE.md)
- [Hybrid RAG & Retrieval Engine Architecture](docs/RAG_ARCHITECTURE_AND_EVALUATION.md)
- [Performance Benchmarks & Empirical Audit](docs/BENCHMARKS.md)
- [Security Policy & Key Management](SECURITY.md)
- [Presentation, Interview Guide & Release Manual](docs/PRESENTATION_AND_RELEASE_GUIDE.md)
- [AI Systems Comprehensive Evaluation Report](docs/evidence/completion/ai_evaluation_report.md)
- [Final Release Pipeline Audit](docs/FINAL_RELEASE_AUDIT.md)

---

## License

SafeRoute LLM Gateway is open-source software licensed under the [MIT License](LICENSE).
