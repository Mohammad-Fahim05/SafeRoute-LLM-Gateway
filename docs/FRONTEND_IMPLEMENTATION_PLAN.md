# SafeRoute LLM Gateway — Premium Frontend Management Console Implementation Plan

## 1. Executive Summary & Objective

The objective is to deliver a complete, production-grade, highly observable, and visually captivating frontend management console for the **SafeRoute LLM Gateway**.

The management console connects to the live backend services:
- **Local Ollama Runtime** for local LLM inference.
- **SQLite Database** (`data/saferoute.db`) for durable request, usage, and client audit logging.
- **Redis Service** for Level 1 exact response caching and Level 2 semantic caching.
- **Prometheus Observability** for real-time counters, gauges, and latency histograms.
- **Security & Guardrail Pipeline** for timing-safe client authentication, rate limiting, and regex/keyword/PII moderation.

---

## 2. Visual Design System: Colorful Indigo-Blue-Violet Identity

To satisfy the strict aesthetic requirement—**no plain black or white backgrounds**—the UI implements a multi-layered, luminous, colorful theme inspired by modern developer infrastructure:

### Color Palette & Design Tokens
- **Main Application Background**: `#11152E` (Deep space indigo)
- **Secondary Background**: `#171D3B` (Layered navy)
- **Sidebar & Header Background**: `#141A35` (Translucent navy-indigo)
- **Primary Card Surface**: `#20284D` (Rich indigo card)
- **Elevated / Popover Surface**: `#28325B` (Brightened indigo surface)
- **Interactive / Hover Surface**: `#303B68` (Vibrant interactive indigo)
- **Primary Violet Accent**: `#9B7BFF` (Luminous violet)
- **Secondary Blue Accent**: `#648CFF` (Bright electric blue)
- **Cyan Accent**: `#35D5E8` (Neon cyan for latency & streaming)
- **Teal Accent**: `#42D6B0` (Mint teal for cache hits & tokens)
- **Status Indicators**:
  - Success: `#4ADEAA` (Emerald teal)
  - Warning: `#F7C66B` (Warm amber)
  - Error: `#FF7D9B` (Rose pink)
- **Typography & Borders**:
  - Primary Text: `#F0F1FF` (Crisp off-white with violet tint)
  - Secondary Text: `#B1BADB` (Muted periwinkle gray)
  - Subtle Borders: `#3A456F` (Defined indigo border)
  - Focus Ring: `#9B7BFF` (Violet focus outline)

---

## 3. Architecture & Tech Stack

### Frontend Architecture
- **Framework**: React 18 + TypeScript (Strict Mode).
- **Build Tool**: Vite (fast HMR, optimized production bundle).
- **Styling**: Tailwind CSS configured with the custom indigo-violet theme tokens.
- **Icons**: Lucide React.
- **Data Visualization**: Recharts (interactive area, bar, and pie charts styled with indigo/violet/teal gradients).
- **State & Data Fetching**: TanStack React Query (auto-refetch, visible-tab polling, stale-while-revalidate).
- **Routing**: React Router v6.
- **Syntax Highlighting & Formatting**: Custom lightweight JSON formatter with copy-to-clipboard actions.

### Directory Structure (`frontend/`)
```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── index.css
    ├── types/
    │   └── index.ts          # Strongly typed models for requests, metrics, providers
    ├── api/
    │   └── client.ts         # Centralized API client with auth injection & error handling
    ├── context/
    │   └── AuthContext.tsx   # Client API key & management token state
    ├── components/
    │   ├── layout/           # AppShell, Sidebar, Header, Breadcrumbs
    │   ├── ui/               # Cards, Buttons, Badges, Modals, Tabs, Skeletons, Tooltips
    │   └── shared/           # JsonViewer, MetricCard, StatusPill, EmptyState
    └── pages/
        ├── Overview.tsx      # High-level KPIs, request throughput, recent requests
        ├── Requests.tsx      # Paginated Request Explorer with search, filters, drawer
        ├── Playground.tsx    # Interactive LLM Playground (streaming SSE, system/user prompt)
        ├── Providers.tsx     # Ollama & Mock model status, routing, and failover
        ├── Cache.tsx         # Exact & Semantic Cache Monitor (Redis hits/misses, TTL)
        ├── Usage.tsx         # Token consumption, cost estimation, CSV export
        ├── Database.tsx      # Read-only SQLite Explorer (tables, schema, records)
        ├── Reliability.tsx   # Errors, rate limits, guardrail blocks, failover logs
        ├── Health.tsx        # Gateway, Redis, SQLite, Ollama health & Prometheus metrics
        ├── Security.tsx      # API key verification, guardrail rules, PII redaction
        └── Config.tsx        # Safe runtime configuration & interactive architecture guide
```

---

## 4. Backend Management API Architecture

To provide real operational data without altering the core OpenAI-compatible proxy path (`/v1/chat/completions`), dedicated read-only management endpoints are implemented in `app/api/management.py` and registered under `/api/management/*`:

1. `GET /api/management/overview`:
   - Summary aggregates: Total requests, success rate, p50/p95 latency, total tokens, cache hit rate, error counts.
   - Timeline data: Hourly/daily request volume, cache hits vs. misses.
2. `GET /api/management/requests`:
   - Server-side paginated, filterable (by status, provider, model, client, error, date) list of request records joined with token usage.
3. `GET /api/management/requests/{request_id}`:
   - Detailed single request view, including attempt sequences, provider latencies, and token cost breakdown.
4. `GET /api/management/database/overview`:
   - SQLite file size, active connection, table row counts, PRAGMA journal mode (`wal`).
5. `GET /api/management/database/tables/{table_name}/records`:
   - Read-only paginated rows for audited tables (`request_records`, `usage_records`, `clients`, `api_key_audits`) with strictly validated table names.
6. `GET /api/management/cache`:
   - Redis ping status, Level 1 exact cache metrics, Level 2 semantic cache metrics, configured TTL, and failure policy.
7. `GET /api/management/providers`:
   - Active provider (`ollama` or `mock`), local Ollama service connectivity, pulled local models (`/api/tags`), allowed models.
8. `GET /api/management/config`:
   - Sanitized settings (timeouts, limits, policies) with all credentials, HMAC secrets, and API keys redacted.
9. `GET /api/management/metrics/summary`:
   - Parsed real-time Prometheus gauges and counters for instant dashboard visualization.

---

## 5. Security & Privacy Guarantees

- **No Prompt Retention**: The SQLite schema does not store raw user prompts or assistant completions. The dashboard displays request metadata (request ID, model, duration, token counts, cache outcome) and explicitly informs operators that payload bodies are not retained for maximum client privacy.
- **Secret Redaction**: API keys, verifier hashes, auth secrets, and Redis connection passwords are never returned in management APIs or bundled into client code.
- **Read-Only Database Inspector**: Database inspection queries use parameterized SQL against an explicit whitelist of tables. Arbitrary SQL execution is strictly disallowed.
- **Authentication**: Management endpoints are protected using the gateway's verified API key authentication mechanism.

---

## 6. Implementation Phases

- [x] **Phase 1: Architecture Audit & Plan Documentation** (Completed).
- [ ] **Phase 2: Backend Management API Implementation & Tests** (`app/api/management.py`).
- [ ] **Phase 3: Frontend Project Scaffolding & Design System Setup** (Vite + React + Tailwind).
- [ ] **Phase 4: Application Shell, Layout & Global State** (Sidebar, TopBar, Auth modal).
- [ ] **Phase 5: Operational Dashboard & Metrics Page** (KPIs, Recharts graphs).
- [ ] **Phase 6: Request Explorer & Detail Drawer** (Filterable, paginated table, JSON viewer).
- [ ] **Phase 7: Interactive LLM Playground** (Real gateway connection, SSE streaming).
- [ ] **Phase 8: Cache Monitor & Redis Observability** (Exact and semantic cache).
- [ ] **Phase 9: SQLite Database Explorer** (Schema, table stats, read-only paginated records).
- [ ] **Phase 10: Provider, Reliability, Security, & System Health Pages**.
- [ ] **Phase 11: Production Build, Test Verification & Documentation**.
