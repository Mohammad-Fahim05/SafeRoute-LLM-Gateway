# SafeRoute LLM Gateway

SafeRoute is a lightweight, reliable, and observable LLM Gateway built with Python and FastAPI. It sits between client applications and AI model providers, standardizing chat completions, enforcing security and authentication, managing timeouts, and providing unified error handling, structured logging, and observability.

---

## Table of Contents
- [What is an LLM Gateway?](#what-is-an-llm-gateway)
- [The Problem SafeRoute Solves](#the-problem-saferoute-solves)
- [Gateway Keys vs. Upstream Provider Keys](#gateway-keys-vs-upstream-provider-keys)
- [Architecture Diagram](#architecture-diagram)
- [Phase Implementation Status](#phase-implementation-status)
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
- [Running the Gateway](#running-the-gateway)
- [API Reference & Examples](#api-reference--examples)
  - [Liveness Check (`GET /health`)](#liveness-check-get-health)
  - [Readiness Check (`GET /ready`)](#readiness-check-get-ready)
  - [Authenticated Chat Completion (`POST /v1/chat/completions`)](#authenticated-chat-completion-post-v1chatcompletions)
  - [Authentication & Validation Error Responses](#authentication--validation-error-responses)
- [Running Tests](#running-tests)
- [Known Limitations & Next Planned Phase](#known-limitations--next-planned-phase)

---

## What is an LLM Gateway?

An **LLM Gateway** is a specialized reverse proxy and API orchestration layer for Large Language Models. Instead of every client application directly calling varied, disparate model providers (such as local Ollama instances, OpenAI, or Anthropic), clients send standard requests to SafeRoute.

The gateway validates requests, authenticates callers, routes to the appropriate backend provider, captures actual token metrics, logs structured audit events without leaking prompt data, and isolates the application from upstream outages.

```
+--------------------+            +------------------------+            +----------------------+
| Client Application |  Bearer    | SafeRoute LLM Gateway  |   Local    | Upstream LLM Backend |
| (Your App / Agent) | ---------> | (Auth, Limits, Proxy)  | ---------> | (Mock or Ollama)     |
|                    | <--------- |                        | <--------- |                      |
+--------------------+  JSON      +------------------------+   HTTP     +----------------------+
```

---

## The Problem SafeRoute Solves

When applications interact directly with model backends, critical engineering problems arise:
1. **Uncontrolled API Access**: Anyone with network access can query costly model backends without authentication or rate controls.
2. **Key Sprawl & Security Risks**: Embedding upstream cloud API keys in frontends or multiple microservices risks credential leakage.
3. **Disparate APIs & Observability Gaps**: Tracking latency, errors, and token usage across different services is nearly impossible without a unified gateway.
4. **Inconsistent Error Behavior**: Raw provider outages or timeouts cause uncaught exceptions or leak stack traces to clients.

SafeRoute solves this by centralizing security, standardized request/response formatting, and robust error normalization.

---

## Gateway Keys vs. Upstream Provider Keys

Understanding the distinction between these two keys is essential:

| Feature | Gateway Client API Key (`gw_test_...`) | Upstream Provider Key (`sk-...`, etc.) |
| :--- | :--- | :--- |
| **Purpose** | Authenticates your client apps to the SafeRoute Gateway. | Authenticates SafeRoute to upstream AI cloud providers (future phases). |
| **Who Has It?** | Your internal microservices, developers, or frontend apps. | Kept strictly private inside SafeRoute's server environment. |
| **Format** | `gw_test_<random_urlsafe_bytes>` | Provider-specific (e.g. OpenAI `sk-...`, Claude `sk-ant-...`). |
| **Storage in Gateway**| **Never stored in plaintext**. Only stored as a keyed HMAC-SHA256 verifier. | Stored encrypted or in environment variables on the gateway server. |
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
        AuthCheck -- Chat Completion Missing / Invalid Key --> 401[Return HTTP 401 Unauthorized]
        AuthCheck -- Valid Key --> Router[FastAPI Chat Router]
        
        Router -->|Validate Model & Request Limits| Allowlist{In Allowed Models?}
        Allowlist -- No --> 400Model[Return 400 Invalid Model]
        Allowlist -- Yes --> ProviderRegistry[Provider Registry]
        
        ProviderRegistry -->|ACTIVE_PROVIDER = 'mock'| MockEngine[MockProvider In-Memory]
        ProviderRegistry -->|ACTIVE_PROVIDER = 'ollama'| OllamaEngine[OllamaProvider AsyncClient]
    end

    subgraph Upstream [Local AI Service]
        OllamaEngine -->|POST /api/chat| OllamaService[Local Ollama Server: 11434]
        OllamaService -->|Raw Response + Tokens| OllamaEngine
    end

    MockEngine -->|Normalized Response| Router
    OllamaEngine -->|Normalized Response| Router
    Router -->|Response Header: X-Request-ID| Client
```

---

## Phase Implementation Status

### Implemented in Phase 1 & 2:
- **Endpoints**: `GET /health`, `GET /ready`, and `POST /v1/chat/completions`.
- **Client Authentication (Phase 2)**: Bearer API key authentication via keyed HMAC-SHA256 (`gw_test_...`).
- **Key Management Utility (Phase 2)**: CLI script (`scripts/manage_keys.py`) to generate keys, show them once, and output safe configuration hashes.
- **Key Revocation (Phase 2)**: Configuration-backed revocation (`enabled: false` or key removal).
- **Ollama Provider Adapter (Phase 2)**: Asynchronous HTTP adapter (`httpx.AsyncClient`) calling local Ollama (`/api/chat`), normalizing responses, and capturing real provider-reported token usage (`prompt_eval_count`, `eval_count`).
- **Provider Switching (Phase 2)**: Toggle `ACTIVE_PROVIDER=mock` or `ACTIVE_PROVIDER=ollama`.
- **Deterministic MockProvider**: Cost-free, in-memory testing engine with error and timeout simulation modes.
- **Request ID Tracking**: Request IDs generated via UUID or validated from incoming `X-Request-ID` headers; tracked via `contextvars`.
- **Structured JSON Logging**: Safe JSON logging that avoids logging prompt content, personal data, or secrets.
- **Standardized Error Responses**: Uniform error JSON format with specific HTTP status codes (400, 401, 413, 422, 502, 504, 500).
- **Automated Test Suite**: 68 unit and integration tests covering authentication, Ollama provider mapping, timeouts, and error isolation.

### NOT Implemented Yet (Scheduled for Future Phases):
- **Cloud Providers**: Claude and Gemini API adapters are **not implemented yet**.
- **Persistent Storage**: No SQLite or PostgreSQL databases yet (keys are currently configuration-backed).
- **Caching**: No Redis, exact response caching, or semantic caching.
- **Vector Search & Embeddings**: No vector databases or embedding models.
- **Rate Limiting & Cost Tracking**: No per-client rate limiters or persistent cost accounting.
- **PII & Prompt Injection Checks**: No content scanning or security classifiers.
- **Streaming (SSE)**: `stream=true` remains explicitly rejected.
- **Containers / K8s**: Docker and container orchestration.

---

## Project Structure

```text
d:/SafeRoute LLM Gateway/
├── .env.example              # Example environment configuration with Phase 2 settings
├── .gitignore                # Git ignore patterns
├── pyproject.toml            # Project packaging and dependencies
├── README.md                 # Complete documentation
├── scripts/
│   └── manage_keys.py        # CLI tool to generate and manage gateway API keys
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI entry point, tracking middleware, lifespan
│   ├── config.py             # Settings using pydantic-settings
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py         # Endpoints with verify_api_key dependency
│   │   └── schemas.py        # Strict Pydantic v2 schemas
│   ├── core/
│   │   ├── __init__.py
│   │   ├── auth.py           # HMAC-SHA256 verification & FastAPI auth dependency
│   │   ├── errors.py         # Standardized error normalization & handlers (401, 502, 504)
│   │   ├── logging.py        # Safe structured JSON logger (redacting secrets)
│   │   └── request_context.py# Request ID and client ID contextvars manager
│   └── providers/
│       ├── __init__.py       # Provider registry & lookup
│       ├── base.py           # Abstract BaseLLMProvider interface
│       ├── mock.py           # Deterministic in-memory mock provider
│       └── ollama.py         # Local Ollama asynchronous HTTP provider adapter
└── tests/
    ├── __init__.py
    ├── conftest.py           # Test settings overrides and authentication fixtures
    ├── unit/
    │   ├── test_auth.py      # HMAC verification and token parsing unit tests
    │   ├── test_config.py    # Config unit tests
    │   ├── test_schemas.py   # Pydantic validation unit tests
    │   ├── test_mock_provider.py # Mock provider & offline isolation tests
    │   └── test_ollama_provider.py # Ollama adapter tests using httpx.MockTransport
    └── integration/
        ├── test_auth_integration.py # 401 missing, malformed, invalid, revoked tests
        ├── test_chat_completions.py # Chat completion integration tests
        ├── test_errors.py    # Timeouts, 502, 504, 400, 422, 500 error tests
        ├── test_health.py    # Public /health and /ready integration tests
        └── test_ollama_integration.py # Ollama provider integration & routing tests
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
pip install fastapi uvicorn pydantic pydantic-settings httpx pytest
```

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
    "is_mock_estimate": false
  }
}
```

*Response Header:* `X-Request-ID: req_8c1b827e8a324ab2a61bb819c9e83f21`

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

---

## Running Tests

Execute the automated test suite with `pytest`:

```bash
pytest -v
```

Expected result:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-8.3.4
collected 68 items

tests/integration/test_auth_integration.py::test_missing_authorization_header_returns_401 PASSED
tests/integration/test_auth_integration.py::test_malformed_bearer_header_returns_401 PASSED
tests/integration/test_auth_integration.py::test_invalid_key_returns_401 PASSED
tests/integration/test_auth_integration.py::test_revoked_key_returns_401 PASSED
tests/integration/test_auth_integration.py::test_valid_key_identifies_correct_client PASSED
tests/integration/test_auth_integration.py::test_auth_rejection_occurs_before_provider_invocation PASSED
tests/integration/test_auth_integration.py::test_auth_misconfigured_fails_safely PASSED
tests/integration/test_auth_integration.py::test_logs_do_not_contain_plaintext_keys_or_secrets PASSED
tests/integration/test_auth_integration.py::test_health_and_ready_endpoints_remain_public PASSED
tests/integration/test_chat_completions.py::test_valid_chat_request_returns_documented_response PASSED
tests/integration/test_chat_completions.py::test_custom_request_id_preserved PASSED
tests/integration/test_chat_completions.py::test_invalid_custom_request_id_replaced_with_safe_id PASSED
tests/integration/test_errors.py::test_empty_messages_rejected PASSED
tests/integration/test_errors.py::test_whitespace_message_content_rejected PASSED
tests/integration/test_errors.py::test_unsupported_fields_rejected PASSED
tests/integration/test_errors.py::test_unsupported_role_rejected PASSED
tests/integration/test_errors.py::test_non_text_content_rejected PASSED
tests/integration/test_errors.py::test_invalid_model_rejected PASSED
tests/integration/test_errors.py::test_invalid_temperature_rejected PASSED
tests/integration/test_errors.py::test_invalid_token_limits_rejected PASSED
tests/integration/test_errors.py::test_token_limit_exceeding_system_max_rejected PASSED
tests/integration/test_errors.py::test_streaming_requests_rejected PASSED
tests/integration/test_errors.py::test_request_id_present_in_error_responses PASSED
tests/integration/test_errors.py::test_mock_provider_timeout_returns_504 PASSED
tests/integration/test_errors.py::test_mock_provider_malformed_returns_502 PASSED
tests/integration/test_errors.py::test_mock_provider_outage_returns_502 PASSED
tests/integration/test_errors.py::test_internal_exception_does_not_leak_stack_traces_or_secrets PASSED
tests/integration/test_errors.py::test_message_limit_exceeded_rejected PASSED
tests/integration/test_errors.py::test_payload_too_large_rejected PASSED
tests/integration/test_health.py::test_health_endpoint_success PASSED
tests/integration/test_health.py::test_ready_endpoint_success PASSED
tests/integration/test_health.py::test_ready_endpoint_failure PASSED
tests/integration/test_ollama_integration.py::test_authenticated_ollama_request_with_mocked_transport PASSED
tests/integration/test_ollama_integration.py::test_unknown_model_rejected_for_ollama PASSED
tests/integration/test_ollama_integration.py::test_authenticated_mock_request_still_works PASSED
tests/unit/test_auth.py::test_generate_api_key_format PASSED
tests/unit/test_auth.py::test_compute_key_verifier_deterministic PASSED
tests/unit/test_auth.py::test_compute_key_verifier_rejects_weak_secret PASSED
tests/unit/test_auth.py::test_extract_bearer_token PASSED
tests/unit/test_auth.py::test_authenticate_client_valid PASSED
tests/unit/test_auth.py::test_authenticate_client_disabled PASSED
tests/unit/test_auth.py::test_authenticate_client_invalid_key PASSED
tests/unit/test_auth.py::test_authenticate_client_missing_auth_secret_fails_closed PASSED
tests/unit/test_config.py::test_default_settings PASSED
tests/unit/test_config.py::test_allowed_models_parsing_from_string PASSED
tests/unit/test_config.py::test_allowed_models_from_list PASSED
tests/unit/test_mock_provider.py::test_mock_provider_deterministic_response PASSED
tests/unit/test_mock_provider.py::test_mock_provider_error_simulation PASSED
tests/unit/test_mock_provider.py::test_mock_provider_malformed_simulation PASSED
tests/unit/test_mock_provider.py::test_mock_provider_makes_no_network_calls PASSED
tests/unit/test_mock_provider.py::test_mock_provider_health_check PASSED
tests/unit/test_ollama_provider.py::test_ollama_successful_response_mapping PASSED
tests/unit/test_ollama_provider.py::test_ollama_missing_usage_handled_as_zero PASSED
tests/unit/test_ollama_provider.py::test_ollama_connection_error PASSED
tests/unit/test_ollama_provider.py::test_ollama_timeout_error PASSED
tests/unit/test_ollama_provider.py::test_ollama_model_not_found PASSED
tests/unit/test_ollama_provider.py::test_ollama_malformed_response PASSED
tests/unit/test_ollama_provider.py::test_ollama_client_cleanup PASSED
tests/unit/test_ollama_provider.py::test_ollama_health_check_probes PASSED
tests/unit/test_schemas.py::test_valid_chat_message PASSED
tests/unit/test_schemas.py::test_chat_message_rejects_empty_content PASSED
tests/unit/test_schemas.py::test_chat_message_rejects_unsupported_role PASSED
tests/unit/test_schemas.py::test_chat_message_forbids_extra_fields PASSED
tests/unit/test_schemas.py::test_valid_chat_completion_request PASSED
tests/unit/test_schemas.py::test_request_rejects_streaming PASSED
tests/unit/test_schemas.py::test_request_forbids_extra_fields PASSED
tests/unit/test_schemas.py::test_request_temperature_bounds PASSED
tests/unit/test_schemas.py::test_request_max_tokens_positive PASSED

============================= 68 passed in 0.92s ==============================
```

---

## Known Limitations & Next Planned Phase

### Known Limitations of Phase 2
- **Configuration-Backed Keys**: Client key verifiers are loaded from `.env` configuration rather than a dynamic database. Changes require restarting the application.
- **Single Active Provider**: Models are routed based on `ACTIVE_PROVIDER` configuration; multi-provider concurrent fallback routing will come in later phases.
- **Local Ollama Availability**: Ollama must be separately installed and running locally for live requests to succeed; if Ollama is not running, the gateway safely returns HTTP 502 (`provider_error`).
- **Claude and Gemini Adapters**: Cloud API adapters for Claude and Gemini are explicitly **not implemented yet**.
- **No Streaming**: SSE streaming (`stream: true`) remains unsupported until Phase 5.

### Next Planned Phase (Phase 3 Preview)
- Persistent SQLite database for client records, API key management, and request metadata.
- Automated usage, latency, and estimated-cost tracking.
