# SafeRoute LLM Gateway — Frontend Architecture

## 1. System Overview

The SafeRoute Frontend is a modern, high-performance Single Page Application (SPA) designed to observe, audit, test, and manage the SafeRoute LLM Gateway in real-time.

### Key Tenets
1. **Strict Colorful Indigo-Blue-Violet Identity**: Zero plain black (`#000000`) or plain white (`#FFFFFF`) backgrounds. Layered surfaces with high-contrast text and subtle glowing accents.
2. **Truthful Observability**: Distinguishes persisted SQLite database history from process-local Prometheus counters and transient browser memory.
3. **Zero-Cost Local AI**: Built specifically for local inference via Ollama (`http://localhost:11434`) and MockProvider test doubles.
4. **Data Isolation & Security**: Never persists raw prompts/completions into browser storage or client-side logs; strictly masks server secrets.

---

## 2. Technology Stack

- **Framework**: React 19 + TypeScript (Strict Mode)
- **Bundler & Dev Server**: Vite 8 with reverse proxy to `http://localhost:8000`
- **Styling**: Tailwind CSS with custom Indigo/Violet/Teal design tokens
- **Icons**: Lucide React
- **Data Fetching & Server State**: TanStack Query (`@tanstack/react-query`)
- **Routing**: React Router (`react-router-dom` v7)
- **Data Visualization**: Recharts (AreaChart, BarChart, PieChart)

---

## 3. Visual System & Design Tokens

| Token Name | Hex Code | Usage |
| :--- | :--- | :--- |
| **Main App Background** | `#11152E` | Body and viewport foundation |
| **Secondary Background** | `#171D3B` | Drawer, header, and filter bars |
| **Sidebar Background** | `#141A35` | Collapsible primary navigation |
| **Primary Card Surface** | `#20284D` | KPI cards, data containers |
| **Elevated Surface** | `#28325B` | Dropdowns, popovers, hovering rows |
| **Interactive Surface** | `#303B68` | Buttons, badge tags, active inputs |
| **Primary Violet** | `#9B7BFF` | Primary actions, glows, brand accents |
| **Secondary Blue** | `#648CFF` | Secondary metric indicators, links |
| **Cyan Accent** | `#35D5E8` | Latency indicators, highlights |
| **Teal Accent** | `#42D6B0` | Cache hit states, success badges |
| **Error Accent** | `#FF7D9B` | Failures, rate-limit throttles |
| **Warning Accent** | `#F7C66B` | Degraded, timeout indicators |
| **Main Text** | `#F0F1FF` | High contrast readable body text |
| **Secondary Text** | `#B1BADB` | Supporting labels, subtitles |
| **Borders** | `#3A456F` | Surface boundaries and dividers |

---

## 4. Application Modules

### 1. Overview Dashboard (`/`)
- Aggregate KPIs: Total Requests, Success Rate, Average Duration, Cache Hit Rate, Token Volumes.
- Interactive 14-day request timeline area chart.
- Model distribution bar and pie charts.
- Recent activity table with direct click-to-inspect drawers.

### 2. Request Explorer (`/requests`)
- Search by Request ID, Model, or Route.
- Multi-dimensional filters (HTTP status, provider, cache state).
- Server-side paginated table with duration and token badges.
- Slide-out Request Detail Drawer detailing routing attempts, token accounting, and SQLite record JSON.
- Displays the Zero-Payload Privacy policy banner explaining why prompts/responses are never stored in SQLite.

### 3. LLM Playground (`/playground`)
- Real-time chat completion interface connected to `/v1/chat/completions`.
- Real SSE chunk-by-chunk streaming display.
- Dynamic model dropdown loaded from Ollama tags.
- Temperature, Max Tokens, System Persona, and Stream toggle controls.
- Stop generation button, duration timer, copy response, and error alert handling.

### 4. Providers & Routing (`/providers`)
- Local Ollama status probe (`/api/tags`), pulled models, parameter sizes, and digest tags.
- MockProvider test double status and synthetic latency metrics.
- Provider capability matrix (Text, Streaming, Tool calling, Failover tiers).
- Explicit architecture note clarifying the permanent pruning of legacy Claude and Gemini integrations.

### 5. Cache & Redis Observability (`/cache`)
- Telemetry across Redis connection ping, exact SHA-256 caching, and semantic vector similarity.
- Exact hit rate percentage and TTL configuration.
- Zero-Drop Fail-Open architecture policy explanation.

### 6. Usage & Token Analytics (`/usage`)
- Token consumption trends and model allocation charts.
- Truthful cost accounting: $0.00 incurred cloud expenses vs simulated avoided cloud API costs.
- Direct CSV export download (`/v1/usage/export`).

### 7. SQLite Database Explorer (`/database`)
- Safe read-only inspection of `data/saferoute.db`.
- SQLite on-disk file size, journal mode (`WAL`), and table row counts.
- Whitelisted table viewer (`clients`, `request_records`, `usage_records`, `api_key_audits`).
- Column definitions, data types, primary key flags, and paginated records.

### 8. Errors & Gateway Reliability (`/reliability`)
- Error category taxonomy (401 client guards, 429 rate throttles, 400 bad requests, 503 provider outages).
- Circuit breaker policies (3 retries with exponential backoff).
- Active fault-tolerance architecture summary.

### 9. System Health & Prometheus (`/health`)
- Component health probes (Gateway Core, SQLite Storage, Redis Cache Broker, Ollama Runtime).
- Live `/metrics` Prometheus stream explorer with real-time text search.

### 10. Security & Guardrail Defenses (`/security`)
- Timing-safe HMAC authentication (`hmac.compare_digest`).
- Automated PII redaction rules (Email, Credit Card, SSN, API Keys).
- Prompt injection heuristic defenses.
- Client isolation guarantees.

### 11. Configuration & Documentation (`/config`)
- Sanitized gateway runtime settings viewer with permanently masked secrets.
- Quick startup runbook cheatsheet with copy-to-clipboard commands.
