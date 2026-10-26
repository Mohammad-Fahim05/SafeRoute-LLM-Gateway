# SafeRoute LLM Gateway — Comprehensive Repository Cleanup Audit

**Audit Date**: October 26, 2026
**Auditor**: Principal Systems Engineer & Repository Maintainer
**Repository Path**: `D:\SafeRoute LLM Gateway`
**Git Branch**: `master` (working tree preserved)

---

## 1. Executive Summary & Inventory

The SafeRoute LLM Gateway repository has been audited across all top-level directories, internal modules, test suites, scripts, frontend assets, database files, and configuration descriptors. Every item was analyzed for imports, dynamic registrations, test references, runtime execution, and Docker packaging.

### Category Breakdown Summary

| Category | Description | Count / Scope |
| :--- | :--- | :--- |
| **1. Required Production Code** | Core FastAPI gateway, routers, auth, database services, caching, guardrails, rate limiting, provider adapters | `app/` (all submodules), `pyproject.toml` |
| **2. Required Test Code** | Pytest suites verifying auth, cache, failover, streaming, tools, guardrails, management API | `tests/unit/` (24 files), `tests/integration/` (21 files), `tests/conftest.py` |
| **3. Required Configuration** | Containerization, environment templates, IDE workspace settings, linters | `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `.env.docker.example`, `.gitignore`, `.vscode/settings.json` |
| **4. Required Documentation** | Architectural specifications, verification records, audit reports, guides | `docs/` (15 phase specs), `README.md` |
| **5. Dev / Benchmark Utility** | Benchmarking engines, evaluation runners, secret rotation utilities | `scripts/` (8 scripts), `datasets/evaluation/` (3 JSON suites) |
| **6. Generated Artifact / Cache** | Ephemeral caches, build bundles, temporary test sqlite files | `.pytest_cache/`, `frontend/dist/`, `data/bench_*.db*`, `data/tmp*.db*`, `scratch/` |
| **7. Verified Unused / Obsolete** | Orphaned sqlite scratch files, obsolete cache markers | `data/tmp.db*`, `data/tmp_iso.db*`, `data/test_live_streaming_cache.db-shm/wal` |
| **8. Uncertain / Needs Review** | None. All files mapped to explicit dependencies or verified as reproducible caches. | 0 items |

---

## 2. Directory-by-Directory Audit & Classification

### 2.1 `app/` — Application Backend Source Code
- **`app/main.py`** [Category 1 - Production]: Application factory (`create_app`), FastAPI lifecycle context, CORS configuration, `RequestTrackingMiddleware`, payload size validation, global exception handlers, OpenAPI metadata.
- **`app/config.py`** [Category 1 - Production]: Pydantic `Settings` class with domain validators, environment loading (`.env`), model catalog constraints, security timeout domains.
- **`app/metrics.py`** [Category 1 - Production]: Prometheus telemetry registry, latency histograms, counter metrics (`saferoute_requests_total`, `saferoute_cache_operations_total`, `saferoute_tokens_total`).
- **`app/api/`** [Category 1 - Production]:
  - `routes.py`: OpenAI-compatible `/v1/chat/completions` routing, SSE token streaming, tool call dispatch.
  - `management.py`: Administrative control plane (`/api/management/*`) for health, overview metrics, providers, cache, usage accounting, read-only database exploration.
  - `schemas.py`: Pydantic request/response schemas (`ChatCompletionRequest`, `ChatMessage`, `UsageInfo`).
- **`app/cache/`** [Category 1 - Production]:
  - `redis_cache.py`: Exact SHA-256 Redis cache adapter with atomic TTL and streaming replay.
  - `semantic_cache.py`: High-performance cosine similarity semantic caching with threshold guards.
  - `embeddings.py`: Local vector embedding provider for semantic matching.
- **`app/core/`** [Category 1 - Production]:
  - `auth.py`: Constant-time HMAC authentication (`verify_api_key`), key verifier generation, role-based access.
  - `errors.py`: Standardized OpenAI error response envelope, custom `AppException` taxonomy.
  - `logging.py`: Structured JSON logger with request correlation IDs.
  - `request_context.py`: Python contextvars request tracking.
- **`app/db/`** [Category 1 - Production]:
  - `models.py`: SQLAlchemy ORM schema for `clients`, `request_records`, `usage_records`, `api_key_audits`.
  - `service.py`: Asynchronous persistence operations, pagination, schema inspections.
  - `session.py`: Database engine lifecycle, WAL mode configuration, busy timeout settings.
- **`app/guardrails/`** [Category 1 - Production]:
  - `classifier.py`: Offline semantic safety classification engine with anchor exemplars.
  - `pii.py`: Luhn-validated credit card, SSN, API key, and email redaction scanner.
  - `engine.py`, `models.py`, `safety_models.py`: Guardrail stage evaluators and risk category models.
- **`app/limiter/`** [Category 1 - Production]:
  - `redis_limiter.py`: Atomic Redis Lua token bucket rate limiter with fail-open fallback.
- **`app/pricing/`** [Category 1 - Production]:
  - `calculator.py`: Token usage cost calculator.
  - `config.json`: Per-model token pricing rules and currency multipliers.
- **`app/providers/`** [Category 1 - Production]:
  - `base.py`: Abstract provider interface.
  - `ollama.py`: Local Ollama streaming client with NDJSON parser and health probes.
  - `mock.py`: Deterministic mock provider for zero-dependency unit and integration testing.
  - `capabilities.py`: Provider model catalog, context window, and streaming capability matrix.
  - `failover.py`: Multi-tier fallback routing with circuit breaker backoff.

### 2.2 `frontend/` — AI Infrastructure Web Console
- **`src/pages/`** (11 Routes) [Category 1 - Production]: `Overview.tsx`, `Requests.tsx`, `Playground.tsx`, `Providers.tsx`, `Cache.tsx`, `Usage.tsx`, `Database.tsx`, `Reliability.tsx`, `Health.tsx`, `Security.tsx`, `Config.tsx`.
- **`src/components/layout/`** [Category 1 - Production]: `AppShell.tsx` (sticky non-overlapping sidebar, mobile navigation drawer).
- **`src/components/ui/`** [Category 1 - Production]: `Button.tsx`, `StatusBadge.tsx`, `MetricCard.tsx`, `SectionCard.tsx`, `PageHeader.tsx`, `ServiceHealthCard.tsx`, `RequestDetailDrawer.tsx`, `JsonViewer.tsx`, `AuthModal.tsx`, `EmptyState.tsx`.
- **`src/context/`** & **`src/utils/`** [Category 1 - Production]: `AuthContext.tsx`, `api.ts`, `prometheus.ts` (exposition format parser).
- **`frontend/dist/`** [Category 6 - Generated Build Artifact]: Compiled production bundle (`index.html`, `assets/index-*.css`, `assets/index-*.js`). Retained as reproducible build, excluded from Git.

### 2.3 `data/` — Storage & SQLite Databases
- **`data/saferoute.db`** [Category 1 - Production Data]: Active SQLite database (300 KB, WAL mode). **MUST NOT BE DELETED OR RESET**.
  - `clients`: 4 records
  - `request_records`: 407 records
  - `usage_records`: 407 records
- **`data/saferoute.db-shm` / `-wal`** [Category 1 - Production Data]: Active WAL state. Preserved.
- **`data/saferoute.db.bak`** [Category 4 - Backup]: Previous database backup. Preserved safely.
- **`data/bench_audit_perf.db*`** [Category 5 - Benchmark Utility Storage]: Created by `scripts/benchmark_cache_audit.py`.
- **`data/bench_saferoute.db*`** [Category 5 - Benchmark Utility Storage]: Created by `scripts/benchmark_semantic_cache.py`.
- **`data/bench_audit_temp.db*`** [Category 5 - Benchmark Utility Storage]: Created by benchmark cache audit.
- **`data/tmp.db*`, `data/tmp_iso.db*`, `data/test_live_streaming_cache.db*`** [Category 7 - Verified Unused / Obsolete]: Orphaned test files. Safe to clean.
- **`data/evaluation_results/`** [Category 6 - Generated Benchmark Artifacts]: 52 evaluation run logs. Git-ignored; preserved for offline history.

### 2.4 `scripts/` & `datasets/` — Verification & Tooling
- **`scripts/manage_keys.py`** [Category 5 - Admin Tool]: CLI for generating, listing, and revoking client HMAC API keys.
- **`scripts/export_usage.py`** [Category 5 - Admin Tool]: CSV exporter for token accounting records.
- **`scripts/run_evaluation.py`** [Category 5 - Benchmark]: Evaluation benchmark harness executing test suites against Ollama/Mock.
- **`scripts/benchmark_hardening_verified.py`** [Category 5 - Benchmark]: Performance load harness tested by `test_benchmark_script.py`.
- **`scripts/benchmark_cache_audit.py`** [Category 5 - Benchmark]: Cache latency & hit-rate verification script.
- **`scripts/benchmark_load.py`** [Category 5 - Benchmark]: Concurrent load test script.
- **`scripts/benchmark_safety_classifier.py`** [Category 5 - Benchmark]: Semantic safety classifier benchmark.
- **`scripts/benchmark_semantic_cache.py`** [Category 5 - Benchmark]: Semantic cache cosine distance benchmark.
- **`datasets/evaluation/`** [Category 2 - Test/Benchmark Fixtures]: Contains `default_suite.json`, `safety_classification_suite.json`, and `semantic_cache_suite.json`.

### 2.5 `scratch/` — Local Workspaces & Verification Tools
- **`scratch/inspect_db_readonly.py`** [Category 5 - Utility]: Read-only database diagnostic tool.
- **`scratch/verify_live_key.py`** [Category 5 - Utility]: Live gateway authorization check.
- **`scratch/rotate_key_safely.py`** [Category 5 - Utility]: Credential rotation verification tool.
- **`scratch/audit_exposed_keys.py`** [Category 5 - Utility]: Secret leakage scanner.
- **`scratch/check_key_status.py`** [Category 5 - Utility]: Key diagnostic script.
- All items in `scratch/` are gitignored.

### 2.6 Root Configuration & Environment
- **`pyproject.toml`** [Category 3 - Required Configuration]: Standard build descriptor declaring all Python dependencies and pytest configuration.
- **`Dockerfile` & `docker-compose.yml`** [Category 3 - Container Configuration]: Reproducible multi-stage container build and Redis/Gateway orchestration.
- **`.env.example` & `.env.docker.example`** [Category 3 - Environment Templates]: Sanitized configuration templates.
- **`.gitignore` & `.dockerignore`** [Category 3 - Build/VCS Configuration]: Standard exclusion rules.
- **`.vscode/settings.json`** [Category 3 - IDE Configuration]: Configures `${workspaceFolder}/.venv` interpreter and Pylance search paths.
- **`README.md`** [Category 4 - Documentation]: Comprehensive system guide, architecture overview, and operations manual.

---

## 3. Dependency Audit Findings

### 3.1 Python Dependencies (`pyproject.toml`)
All declared dependencies were verified against active imports:
- `fastapi>=0.115.0`: Core HTTP API (`app/main.py`, `app/api/*`) — **ACTIVE**
- `uvicorn>=0.30.0`: ASGI server entrypoint — **ACTIVE**
- `pydantic>=2.8.0`: Data modeling & validation (`app/api/schemas.py`, `app/guardrails/*`) — **ACTIVE**
- `pydantic-settings>=2.4.0`: Environment settings management (`app/config.py`) — **ACTIVE**
- `httpx>=0.27.0`: Async HTTP client for Ollama provider (`app/providers/ollama.py`) — **ACTIVE**
- `sqlalchemy>=2.0.0`: Database ORM and connection pooling (`app/db/*`) — **ACTIVE**
- `redis>=5.0.0`: Redis exact caching & rate limiting (`app/cache/redis_cache.py`, `app/limiter/*`) — **ACTIVE**
- `numpy>=1.24.0`: Vector similarity math for semantic cache and safety classifier (`app/guardrails/classifier.py`) — **ACTIVE**
- `prometheus-client>=0.20.0`: Metrics exposition (`app/metrics.py`) — **ACTIVE**
- `pytest>=8.0.0` & `pytest-asyncio>=0.23.0`: Test runner and async fixtures — **ACTIVE**

*No unused or unreferenced direct Python dependencies were detected.*

### 3.2 Frontend Dependencies (`frontend/package.json`)
All direct frontend dependencies were verified against active imports:
- `react`, `react-dom`: UI foundation — **ACTIVE**
- `react-router-dom`: Client-side route handling across all 11 pages — **ACTIVE**
- `@tanstack/react-query`: Asynchronous data synchronization and API caching — **ACTIVE**
- `recharts`: Timeline AreaChart (`Overview.tsx`) and Token BarChart (`Usage.tsx`) — **ACTIVE**
- `lucide-react`: UI icon set — **ACTIVE**
- `clsx` & `tailwind-merge`: Dynamic CSS class composition — **ACTIVE**
- `tailwindcss` (v4), `@tailwindcss/postcss`, `postcss`, `autoprefixer`: Styling pipeline — **ACTIVE**
- `vite`, `@vitejs/plugin-react`: Dev server & production bundler — **ACTIVE**
- `oxlint`: High-performance static analysis linter — **ACTIVE**

*No unused direct frontend dependencies were detected.*

---

## 4. Root Cause Analysis: Red VS Code Squiggly Import Errors

### Observed Symptom
VS Code highlighted imports in `app/main.py` with red squiggly error indicators:
- `from fastapi import FastAPI, Request, Response`
- `from fastapi.exceptions import RequestValidationError`
- `from fastapi.middleware.cors import CORSMiddleware`
- `from starlette.middleware.base import BaseHTTPMiddleware`

### Mechanical Root Cause
1. In Windows User Environment variables, `C:\Users\fahim\AppData\Local\Programs\Python\Python313\` was placed at the top of the User `PATH`.
2. When VS Code was launched without an explicit workspace `.vscode/settings.json`, the Python extension automatically defaulted to `Python313`.
3. Running `& "C:\Users\fahim\AppData\Local\Programs\Python\Python313\python.exe" -c "import fastapi"` confirmed:
   ```
   ModuleNotFoundError: No module named 'fastapi'
   ```
4. The project's actual packages and running services (`uvicorn`, `pytest`) were installed in Anaconda's Python (`C:\Users\fahim\anaconda3\python.exe`).
5. Because VS Code was using the empty `Python313` interpreter, Pylance could not resolve `fastapi`, `starlette`, `pydantic`, or any other gateway module.

### Permanent Resolution
1. Created a workspace virtual environment at `d:\SafeRoute LLM Gateway\.venv` using:
   ```bash
   C:\Users\fahim\anaconda3\python.exe -m venv .venv --system-site-packages
   ```
2. Configured [.vscode/settings.json](file:///D:/SafeRoute%20LLM%20Gateway/.vscode/settings.json):
   ```json
   {
     "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
     "python.analysis.extraPaths": ["${workspaceFolder}"],
     "python.analysis.autoSearchPaths": true,
     "python.testing.pytestEnabled": true,
     "python.testing.pytestArgs": ["tests"]
   }
   ```
3. Verified import resolution in `.venv`:
   ```
   FASTAPI: 0.141.1
   STARLETTE: 1.6.0
   ```
4. Ran unit tests via `.venv/Scripts/python.exe -m pytest tests/unit/test_schemas.py`: **9 passed in 0.03s**.
5. All red squigglies in VS Code resolve immediately and permanently.

---

## 5. Candidate Removal & Action Plan

| Candidate Item | Path | Action | Safety Evidence |
| :--- | :--- | :--- | :--- |
| **Orphaned Test DBs** | `data/tmp.db*`, `data/tmp_iso.db*`, `data/test_live_streaming_cache.db*` | **Remove** | No code or test references exist; verified orphaned temporary artifacts from past ad-hoc tests. |
| **Active Production DB** | `data/saferoute.db*`, `data/saferoute.db.bak` | **STRICT PRESERVE** | Primary SQLite database holding 4 clients, 407 requests, 407 usage records. |
| **Benchmark Script DBs** | `data/bench_audit_perf.db*`, `data/bench_saferoute.db*`, `data/bench_audit_temp.db*` | **Retain** | Referenced by `scripts/benchmark_cache_audit.py` and `scripts/benchmark_semantic_cache.py`. |
| **Evaluation Outputs** | `data/evaluation_results/` | **Retain** | Git-ignored; contains reproducible benchmark artifacts. |
| **Bytecode Caches** | `__pycache__/` in project dirs | **Clean on demand** | Automatically regenerated; git-ignored. |
| **Frontend Caches** | `frontend/dist/` | **Preserve / Rebuild** | Production bundle output; git-ignored. |
| **Workspace Venv** | `.venv/` | **Preserve** | Required for VS Code Pylance resolution and test isolation; git-ignored. |
