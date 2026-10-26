# Phase 9.2 — SafeRoute LLM Gateway: Streaming Responses

## Executive Summary

Phase 9.2 introduces production-grade, asynchronous streaming chat completions (`stream: true`) to the SafeRoute LLM Gateway using the standard Server-Sent Events (SSE, `Content-Type: text/event-stream`) protocol.

All existing non-streaming gateway capabilities—including HMAC-SHA256 client authentication, request validation, allowed-model enforcement, client rate limiting, input and output safety guardrails, SQLite request and usage persistence, exact-match caching isolation, and Phase 9.1 multi-provider failover—are strictly preserved.

---

## 1. Streaming API Contract

### Request Specification
Clients request a streaming response by setting `"stream": true` on `POST /v1/chat/completions`.

```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    {"role": "user", "content": "Explain asynchronous event streaming in 3 bullet points."}
  ],
  "stream": true,
  "temperature": 0.7
}
```

### Response Headers
When `stream: true`, the gateway commits HTTP 200 with the following headers:
- `Content-Type: text/event-stream; charset=utf-8`
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Request-ID`: Gateway correlation identifier (e.g. `req_abc123`)
- `X-Serving-Provider`: Upstream provider serving the stream (`mock`, `claude`, `gemini`, `ollama`)
- `X-Serving-Model`: Concrete model delivering the stream (reflects fallback model if failover occurred)
- `X-Requested-Model`: The original model requested by the client
- `X-Failover-Occurred`: `"true"` if pre-stream fallback occurred; `"false"` otherwise
- `X-Failover-Attempts`: Number of provider attempts made before streaming began
- `X-Cache`: `BYPASS` (streaming responses bypass cache storage and retrieval)
- `X-RateLimit-*`: Standard rate-limit headers when rate limiting is enabled

### Server-Sent Event (SSE) Protocol Format
The gateway yields chunks conforming to OpenAI-compatible event lines (`data: <json>\n\n`):

#### 1. Content Chunk
```text
data: {"id":"chatcmpl-claude-msg_123","object":"chat.completion.chunk","created":1792900000,"model":"claude-sonnet-4-6","choices":[{"index":0,"delta":{"role":"assistant","content":"Here "},"finish_reason":null}]}

data: {"id":"chatcmpl-claude-msg_123","object":"chat.completion.chunk","created":1792900000,"model":"claude-sonnet-4-6","choices":[{"index":0,"delta":{"content":"are "},"finish_reason":null}]}
```

#### 2. Terminal Chunk (with Provider Usage)
```text
data: {"id":"chatcmpl-claude-msg_123","object":"chat.completion.chunk","created":1792900000,"model":"claude-sonnet-4-6","choices":[{"index":0,"delta":{"content":""},"finish_reason":"stop"}],"usage":{"prompt_tokens":14,"completion_tokens":42,"total_tokens":56,"is_mock_estimate":false,"usage_source":"provider_reported"}}
```

#### 3. Completion Signal
```text
data: [DONE]
```

#### 4. Mid-Stream Error Event
If upstream fails *after* content has already been sent to the client:
```text
data: {"error":{"message":"Upstream provider error during streaming response.","type":"stream_error","code":"provider_error","request_id":"req_abc123"}}

data: [DONE]
```

---

## 2. Supported Provider Adapters

All 4 provider adapters implement `async def stream_complete(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]`:

| Provider | Upstream Transport | Streaming Endpoint | Usage Extraction |
|---|---|---|---|
| **Anthropic Claude** | HTTP SSE (`POST /v1/messages`, `stream: true`) | Anthropic API | Extracted from `message_start.message.usage.input_tokens` and `message_delta.usage.output_tokens`. Missing usage preserved as `null`. |
| **Google Gemini** | HTTP SSE (`POST /v1beta/models/{model}:streamGenerateContent?alt=sse`) | Google AI Studio / Gemini API | Extracted from `usageMetadata` (`promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`). Missing usage preserved as `null`. |
| **Ollama** | NDJSON Stream (`POST /api/chat`, `stream: true`) | Local Ollama Service | Extracted from `prompt_eval_count` and `eval_count` on final line (`done: true`). |
| **Mock Provider** | In-Memory Async Generator | Local / Unit Test | Deterministic word-boundary chunking, supporting empty, short, timeout, error, and mid-stream failure simulations. |

### Adapter Normalization & Provider-Specific Differences
- **Role Emission**: Anthropic Claude emits `message_start` before any text, while Gemini and Ollama emit role with the first text chunk. The gateway normalizes this by ensuring `role="assistant"` is emitted on chunk #0 across all providers.
- **Terminal Event**: Claude emits `message_stop`, Gemini sets `finishReason: "STOP"`, and Ollama sets `done: true`. The gateway maps all to an explicit stop chunk followed by `data: [DONE]\n\n`.
- **Token Counts**: When providers report partial or omitted token counts (e.g., interrupted stream), SafeRoute preserves `output_tokens` and `total_tokens` as `null` rather than falsifying them to zero.

---

## 3. Client Consumption Examples

### Python (`httpx`)
```python
import httpx
import json

url = "http://localhost:8000/v1/chat/completions"
headers = {
    "Authorization": "Bearer gw_test_your_client_key_here",
    "Content-Type": "application/json",
}
payload = {
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Tell me a short story."}],
    "stream": True,
}

with httpx.stream("POST", url, headers=headers, json=payload, timeout=30.0) as response:
    for line in response.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        chunk = json.loads(data_str)
        if "error" in chunk:
            print(f"\n[STREAM ERROR]: {chunk['error']['message']}")
            break
        delta = chunk["choices"][0]["delta"].get("content", "")
        print(delta, end="", flush=True)
print()
```

### JavaScript / TypeScript (`fetch`)
```typescript
const response = await fetch("http://localhost:8000/v1/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": "Bearer gw_test_your_client_key_here",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "gemini-3.8-flash",
    messages: [{ role: "user", content: "Write a haiku." }],
    stream: true,
  }),
});

const reader = response.body?.getReader();
const decoder = new TextDecoder();

while (reader) {
  const { done, value } = await reader.read();
  if (done) break;
  const chunkText = decoder.decode(value);
  for (const line of chunkText.split("\n")) {
    if (line.startsWith("data:")) {
      const payload = line.replace("data:", "").trim();
      if (payload === "[DONE]") break;
      const data = JSON.parse(payload);
      if (data.error) {
        console.error("Stream error:", data.error);
        break;
      }
      process.stdout.write(data.choices[0]?.delta?.content || "");
    }
  }
}
```

---

## 4. Security & Safety Lifecycle

All security validations are executed **strictly before** any HTTP headers or streaming events are committed:

```
[Incoming Request (stream: true)]
             │
             ▼
 1. Authenticate Client API Key (HMAC-SHA256) ──[Invalid]──► HTTP 401 JSON
             │
             ▼
 2. Verify Model Allowlist ─────────────────────[Blocked]──► HTTP 400 JSON
             │
             ▼
 3. Enforce Safety Limits & Request Schema ─────[Invalid]──► HTTP 422 JSON
             │
             ▼
 4. Enforce Client Rate Limits (Fixed Window) ──[Exceeded]─► HTTP 429 JSON
             │
             ▼
 5. Input Guardrails Inspection ────────────────[Blocked]──► HTTP 400 JSON
             │
             ▼
 6. Pre-Stream Failover Liveness Check ─────────[All Fail]─► HTTP 502/504 JSON
             │ (Chunk #0 Acquired)
             ▼
[HTTP 200 Headers Sent: Content-Type: text/event-stream]
             │
             ▼
 7. Incremental Output Guardrail Evaluation
             │
             ▼
[SSE Chunks Emitted: data: {...}\n\n]
             │
             ▼
[Terminal Event: data: [DONE]\n\n]
```

### Incremental Output Guardrails & Safety Policy
As each incremental chunk arrives from the provider:
1. `delta.content` is appended to `accumulated_text`.
2. `guardrail_engine.inspect_output(accumulated_text)` evaluates all configured output rules.
3. If an output rule matches:
   - The violating chunk is blocked (not yielded).
   - The stream terminates immediately with an error event:
     `data: {"error": {"message": "Content was blocked by output safety guardrails.", "type": "guardrail_error", "code": "output_guardrail_blocked", "rule_id": "...", "request_id": "..."}}\n\n`
   - `data: [DONE]\n\n` is sent.
   - The stream outcome is persisted as `failed` with `stream_status="failed_post_stream"` and `error_code="output_guardrail_blocked"`.

> **Fundamental Streaming Trade-off**: In an unbuffered SSE stream, tokens transmitted in earlier chunks have already crossed the network to the client. Incremental evaluation halts the response immediately upon detecting a violation, but cannot retract previously delivered text. For applications requiring zero content exposure before validation, non-streaming completions or client-side buffering must be used.

---

## 5. Failure Handling, Retries, and Failover Invariants

### Pre-Stream vs. Post-Stream Failure Handling

| Failure Timing | Allowed Failover / Retry | Client-Facing Response | SQLite Outcome |
|---|---|---|---|
| **Pre-Stream** (before Chunk #0 emitted) | **Permitted**. Phase 9.1 multi-provider failover attempts configured fallback models. | If all fail: standard HTTP error status (429, 502, 504) with JSON error body. If a fallback succeeds: HTTP 200 `text/event-stream` with `X-Failover-Occurred: true`. | `status="failed"`, `stream_status="failed_pre_stream"` (if all fail); or `status="success"`, `stream_status="completed"`, `failover_occurred=True` (if fallback succeeds). |
| **Post-Stream** (after content emitted) | **Strictly Forbidden**. Never stitch another model's output into an active stream. | HTTP headers are already committed. Gateway emits a sanitized `data: {"error": ...}\n\n` event followed by `data: [DONE]\n\n`. | `status="failed"`, `stream_status="failed_post_stream"`, `error_code="provider_error"`. |

### Client Disconnection & Resource Cleanup
- Starlette/FastAPI raises `asyncio.CancelledError` inside the streaming generator when the client disconnects prematurely.
- The generator's `except asyncio.CancelledError:` block catches the cancellation, releases upstream connections via `aclose()`, and logs the disconnect.
- The `finally:` block executes durably, persisting the outcome in SQLite with `status="failed"`, `stream_status="cancelled"`, and HTTP status `499`.

---

## 6. Usage, Cost, and Persistence Semantics

### Token Provenance During Streaming
- **Provider Reported**: Captured when providers report token usage in final chunks (Anthropic `message_delta`, Gemini `usageMetadata`, Ollama `eval_count`).
- **Unavailable**: If an interrupted stream or provider omits token usage, `input_tokens`, `output_tokens`, and `total_tokens` are recorded as `null` (`None`). SafeRoute **never** treats missing usage as zero.
- **Cost Estimation**: The pricing engine calculates estimated cost **only** when both input and output token counts are known non-null values. Missing token counts produce `null` cost estimates.

### Database Schema Updates (`request_records`)
Two columns were added with automatic backward-compatible SQLite migration:
- `stream: BOOLEAN` (default `0`) — Distinguishes streaming completions from non-streaming completions.
- `stream_status: VARCHAR(32)` (nullable) — Detailed stream outcome:
  - `"completed"` — Stream finished normally through terminal event.
  - `"failed_pre_stream"` — Provider failed before emitting any chunks.
  - `"failed_post_stream"` — Upstream failure or guardrail block after partial output.
  - `"cancelled"` — Client disconnected before stream completion.

---

## 7. Caching Isolation Policy

Streaming completions **bypass exact-match caching completely**:
- Inbound streaming requests are not checked against Redis (`X-Cache: BYPASS`).
- Outbound streaming responses are never written to Redis cache.
- Prevents cross-protocol cache contamination and ensures non-streaming requests never receive partial or raw SSE frames from cache.

---

## 8. Verification & Test Suite Execution

All unit, integration, and evaluation suites were executed locally against the implementation:

### 1. Focused Streaming Unit Tests
```bash
pytest tests/unit/test_streaming.py -v
```
**Result**: `8 passed in 0.88s`
- Verified MockProvider multi-chunk order, empty response, short response, timeouts, errors, and programmatic mid-stream failure.
- Verified ClaudeProvider SSE parsing, delta concatenation, and token usage extraction.
- Verified GeminiProvider SSE parsing and `usageMetadata` extraction.
- Verified OllamaProvider ndjson parsing and eval counts extraction.
- Verified `init_stream_with_failover` pre-stream candidate retry and fallback resolution.

### 2. Comprehensive Streaming Integration Tests
```bash
pytest tests/integration/test_streaming_integration.py -v
```
**Result**: `21 passed in 3.80s`
- Verified all 22 required architectural scenarios:
  1. Non-streaming unchanged.
  2. SSE Content-Type and event format.
  3. Ordered chunk delivery.
  4. Terminal `[DONE]` event.
  5. Empty and short completions.
  6. Auth failure before streaming (HTTP 401 JSON).
  7. Invalid model rejected before streaming (HTTP 400 JSON).
  8. Input guardrail rejection before streaming (HTTP 400 JSON).
  9. Client rate limiting enforced before streaming (HTTP 429 JSON).
  10. Provider failure before first chunk returns HTTP 502 JSON.
  11. Provider failure after partial output emits sanitized error event.
  12. Cross-provider retry strictly prohibited after content emission.
  13. Pre-stream failover records actual serving model and failover headers.
  14-15. Client cancellation stops upstream generation and executes cleanup.
  16. Missing usage remains null rather than zero.
  17. Partial streams persisted as failed with `stream_status="failed_post_stream"`.
  18. Output guardrail triggers error event and terminates stream.
  19. Cache isolation preserves `X-Cache: BYPASS`.
  20. Request IDs and failover audit records persisted accurately.
  21. Adapters adhere to uniform SSE schema.
  22. Concurrent streaming requests maintain complete state isolation.

### 3. Full Repository Test Suite
```bash
pytest -q
```
**Result**: `282 passed in 16.32s` (100% pass rate, zero failures, zero regressions across Phases 1–9.2).

### 4. Reproducible Evaluation Suite
```bash
python scripts/run_evaluation.py --mode quick
```
**Result**: `14 passed, 0 failed, 1 skipped (live optional), 100% pass rate in 741.92ms`.

---

## 9. Remaining Limitations

1. **Incremental Guardrail Token Exposure**: As documented in Section 4, tokens emitted before a guardrail violation match cannot be recalled over the wire.
2. **Live Cloud Streaming Verification**: Test suites use deterministic in-memory and mock HTTP transports (`httpx.MockTransport`) without making live network calls to paid APIs. Live cloud execution requires valid user-provisioned API keys.
3. **Chunk Boundary Alignment**: Highly fragmented network packets from remote upstream servers depend on HTTP transport chunk decoding; chunk aggregation is normalized at the line level.

---

## 10. Conclusion & Next Phase Recommendation

Phase 9.2 is complete and verified. The SafeRoute gateway reliably supports streaming completions while upholding all security, governance, rate-limiting, and persistence guarantees.

**Recommended Next Phase**: **Phase 9.3 — Semantic Caching or Function/Tool-Calling Normalization**.
