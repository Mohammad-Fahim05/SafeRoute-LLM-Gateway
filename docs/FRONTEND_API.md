# SafeRoute LLM Gateway — Management API Reference

The Management API (`/api/management/*`) powers the SafeRoute Management Console. All endpoints return standard JSON responses and enforce appropriate security and bounds.

---

## 1. Authentication Endpoints

### `GET /api/management/auth/status`
Reports gateway authentication enforcement and client configuration.
- **Auth Required**: No
- **Response**:
```json
{
  "auth_enabled": true,
  "key_prefix": "gw_test_",
  "registered_clients_count": 4
}
```

### `POST /api/management/auth/verify`
Validates a client API key against the server's registered HMAC digests using constant-time comparison.
- **Request Body**:
```json
{
  "api_key": "gw_test_example..."
}
```
- **Response**:
```json
{
  "valid": true,
  "client_id": "test_client_1"
}
```

---

## 2. Telemetry & Requests Endpoints

### `GET /api/management/overview`
Returns aggregate gateway metrics, duration percentiles, cache hits, token volumes, and 14-day timeline.
- **Response**:
```json
{
  "total_requests": 154,
  "successful_requests": 154,
  "failed_requests": 0,
  "success_rate": 100.0,
  "avg_duration_ms": 28.4,
  "p50_duration_ms": 24.1,
  "p95_duration_ms": 48.2,
  "p99_duration_ms": 62.0,
  "exact_cache_hits": 45,
  "semantic_cache_hits": 0,
  "total_cache_hits": 45,
  "cache_misses": 109,
  "cache_hit_rate": 29.2,
  "total_input_tokens": 12840,
  "total_output_tokens": 8420,
  "total_tokens": 21260,
  "estimated_total_cost": 0.0,
  "timeline": [...],
  "recent_requests": [...]
}
```

### `GET /api/management/requests`
Returns a paginated, filterable list of request records joined with token accounting.
- **Query Parameters**:
  - `page` (int, default 1)
  - `page_size` (int, default 25, max 100)
  - `search` (optional string)
  - `status` (optional int, e.g. 200, 429)
  - `provider` (optional string, e.g. "ollama", "mock")
  - `cache_status` (optional string, e.g. "HIT", "MISS")

### `GET /api/management/requests/{id}`
Returns granular metadata, failover attempts sequence, usage numbers, and retention policy for a single request.

---

## 3. Database Explorer Endpoints

### `GET /api/management/database/overview`
Inspects active SQLite database metrics without altering or running expensive operations.
- **Response**:
```json
{
  "database_url": "sqlite:///data/saferoute.db",
  "database_path": "data/saferoute.db",
  "file_size_bytes": 110592,
  "journal_mode": "wal",
  "read_only": true,
  "tables": [
    {
      "table_name": "request_records",
      "row_count": 154,
      "columns": [...]
    }
  ]
}
```

### `GET /api/management/database/tables/{table}/records`
Returns bounded, paginated records for a strictly whitelisted table (`clients`, `request_records`, `usage_records`, `api_key_audits`).
- **Safety**: Rejects arbitrary SQL queries and unlisted table names.

---

## 4. Cache & Providers Endpoints

### `GET /api/management/cache`
Pings Redis and inspects exact/semantic cache configuration and hit rates.

### `GET /api/management/providers`
Probes local Ollama at `http://localhost:11434/api/tags`, returns active pulled models, and presents the provider capability matrix.

---

## 5. Health & Config Endpoints

### `GET /api/management/health/summary`
Reports readiness across Gateway Core, SQLite Database, Redis Cache Broker, and Ollama Runtime.

### `GET /api/management/config`
Returns sanitized gateway settings with all secrets permanently masked (`***REDACTED***`).
