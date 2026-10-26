# Phase 9.3 — SafeRoute LLM Gateway: Unified Tool / Function-Calling Normalization

## Executive Summary

Phase 9.3 introduces unified, provider-neutral tool/function-calling normalization to the SafeRoute LLM Gateway without breaking existing chat completions, failover, streaming, guardrails, caching, or usage tracking.

**Mandatory Security Boundary:** SafeRoute operates strictly as an AI API gateway and normalizer. It **never** executes arbitrary tool code, Python scripts, shell commands, SQL queries, or network requests requested by a model. Tool invocations requested by the model are parsed, validated, and returned to the calling application with `finish_reason: "tool_calls"`. The consuming client application retains full authority over whether and how to execute tools.

---

## 1. Architecture & Execution Boundary

```
+---------------------------------------------------------------------------------------+
|                                  Calling Client                                      |
+---------------------------------------------------------------------------------------+
     |                                                                   ^
     | 1. POST /v1/chat/completions (with tools)                         | 3. Response:
     |    or follow-up with tool results                                 |    finish_reason: "tool_calls"
     v                                                                   |    tool_calls: [...]
+---------------------------------------------------------------------------------------+
|                                SafeRoute LLM Gateway                                  |
|                                                                                       |
|  [Schema Validation] -> Max 32 tools, 32KB schema, valid tool choice                  |
|  [Input Guardrails]  -> Safety & sensitive redaction check (content + tool args)       |
|  [Rate Limiter]      -> Client-level token/request quotas                             |
|  [Cache Lookup]      -> Canonical key with tools + tool_choice SHA-256                |
|  [Failover Router]   -> Validates fallback model supports tool capabilities           |
|                                                                                       |
|  Provider Translation:                                                                |
|    - Claude: tools -> input_schema, assistant tool_calls -> tool_use blocks           |
|              tool messages -> user tool_result blocks                                 |
|    - Gemini: tools -> functionDeclarations, assistant tool_calls -> functionCall      |
|              tool messages -> functionResponse inside user turn                       |
|    - Ollama: tools -> OpenAI-compatible tools (validated against model support)       |
|    - Mock:   Deterministic tool calls & fragments for automated verification          |
|                                                                                       |
|  Normalizer: Parses upstream tool requests into OpenAI-compatible format               |
|  Output Guardrails: Inspects tool arguments before dispatch                           |
|  Persistence: Logs request, provider usage & costs to SQLite audit trail             |
|                                                                                       |
|  * STRICT BOUNDARY: NO TOOL EXECUTION OCCURS INSIDE SAFEROUTE GATEWAY *               |
+---------------------------------------------------------------------------------------+
     |                                                                   ^
     | Upstream Provider Request                                         | Upstream Provider Response
     v                                                                   | (Raw tool_use / functionCall)
+---------------------------------------------------------------------------------------+
|                       Upstream AI Providers (Claude / Gemini / Ollama)               |
+---------------------------------------------------------------------------------------+
```

### Security & Non-Execution Guarantees
1. **Zero Execution:** SafeRoute never interprets a tool name as permission to invoke external APIs or execute code.
2. **Schema Conformance:** Client-supplied tool definitions are validated against strict JSON Schema bounds (maximum 32 tools, maximum 32 KB per parameter schema, duplicate name prevention).
3. **Data Sanitization:** Malformed arguments returned by upstream models produce safe structured errors or raw-string preservation; they are never mutated into different executable commands.
4. **Credential and Parameter Redaction:** Tool arguments are inspected for safety guardrails and excluded from security audit logs to prevent credential leakage.

---

## 2. Normalized Request Schema

SafeRoute adopts the OpenAI-compatible function and tool specification:

```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    {
      "role": "user",
      "content": "What's the weather in Seattle, WA in Fahrenheit?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_current_weather",
        "description": "Get the current weather for a given location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "The city and state, e.g. San Francisco, CA"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"]
            }
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0.0
}
```

### Supported `tool_choice` Values
- `"auto"`: Model decides whether to call a tool or respond with text (default).
- `"none"`: Model is prohibited from generating tool calls and must respond with text.
- `"required"`: Model must call one or more tools (mapped to `"any"` for Anthropic Claude, and `"ANY"` for Google Gemini).
- `{"type": "function", "function": {"name": "get_current_weather"}}`: Model is forced to call the specified function. Validated against the supplied `tools` list.

### Validation Rules
- **Maximum Tools:** 32 tools per request.
- **Maximum Schema Size:** 32,768 characters per tool `parameters` JSON schema.
- **Unique Tool Names:** Duplicate tool names are rejected with HTTP 422.
- **Tool Name Syntax:** Function names must match `^[a-zA-Z0-9_-]{1,64}$`.
- **Model Compatibility:** If a request includes `tools`, the target model must support tool calling; otherwise, the request is rejected with HTTP 400 (`unsupported_parameter`).

---

## 3. Normalized Response Schema

When an upstream model invokes one or more tools, SafeRoute returns:

```json
{
  "id": "chatcmpl-claude-msg_01Abc",
  "object": "chat.completion",
  "created": 1740000000,
  "model": "claude-sonnet-4-6",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "toolu_01AbcDef",
            "type": "function",
            "function": {
              "name": "get_current_weather",
              "arguments": "{\"location\":\"Seattle, WA\",\"unit\":\"fahrenheit\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 128,
    "completion_tokens": 34,
    "total_tokens": 162,
    "is_mock_estimate": false,
    "usage_source": "provider_reported"
  }
}
```

---

## 4. Provider Capability Matrix & Translation Mechanics

| Provider | Model Family | Tool Support | Native Format | Tool Choice Mapping |
|---|---|---|---|---|
| **Anthropic Claude** | `claude-sonnet-4-6`<br>`claude-haiku-4-5-20251001`<br>`claude-opus-4-5-20251101`<br>`claude-3-5-sonnet-20241022` | Supported | `tools[].input_schema`<br>`content_block: tool_use` | `auto` -> `{"type":"auto"}`<br>`required` -> `{"type":"any"}`<br>`{"type":"function",...}` -> `{"type":"tool","name":"..."}` |
| **Google Gemini** | `gemini-2.5-flash`<br>`gemini-2.5-pro`<br>`gemini-2.0-flash` | Supported | `tools[].functionDeclarations`<br>`parts[].functionCall` | `auto` -> `MODE_AUTO`<br>`none` -> `MODE_NONE`<br>`required` -> `MODE_ANY`<br>named -> `MODE_ANY` with `allowedFunctionNames` |
| **Ollama** | `llama3`, `llama3.1`, `mistral`, `qwen2.5` | Supported | OpenAI-compatible `tools` array | Passed directly if supported |
| **Ollama** | `phi3` | Unsupported | Rejected with HTTP 400 | N/A |
| **Mock Provider** | `mock-model` | Deterministic | Returns synthetic tool calls | Simulates single, multi, and malformed calls |

### Provider Message Translation Details

#### Anthropic Claude
- Anthropic Claude requires role alternation (`user` -> `assistant` -> `user`).
- Tool calls emitted by Claude arrive as assistant blocks with `type: "tool_use"`, `id`, `name`, and `input` dictionary. SafeRoute normalizes these to `ChatCompletionMessageToolCall`.
- Tool results sent back by the client (`role: "tool"`, `tool_call_id`, `content`) are mapped into `tool_result` content blocks inside a `user` turn. Multiple consecutive tool results are coalesced into a single `user` turn with multiple `tool_result` blocks.

#### Google Gemini
- Gemini represents functions via `functionCall` and `functionResponse` parts.
- Tool responses (`role: "tool"`) cannot be sent as top-level roles. SafeRoute maps them to `functionResponse` parts inside `user` turns, preserving the function name and structured response.

---

## 5. Streaming Tool Calling Contract

When `stream: true` is requested alongside `tools`, SafeRoute streams normalized chunk deltas conforming to the OpenAI streaming tool call standard:

```text
data: {"id":"chatcmpl-mock-123","object":"chat.completion.chunk","created":1740000000,"model":"mock-model","choices":[{"index":0,"delta":{"role":"assistant","content":null,"tool_calls":[{"index":0,"id":"call_mock_123","type":"function","function":{"name":"get_weather","arguments":""}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-mock-123","object":"chat.completion.chunk","created":1740000000,"model":"mock-model","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"loc"}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-mock-123","object":"chat.completion.chunk","created":1740000000,"model":"mock-model","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ation\": \"Seattle\"}"}}]},"finish_reason":null}]}

data: {"id":"chatcmpl-mock-123","object":"chat.completion.chunk","created":1740000000,"model":"mock-model","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":45,"completion_tokens":22,"total_tokens":67,"is_mock_estimate":true,"usage_source":"mock_generated"}}

data: [DONE]
```

### Streaming Guarantees:
- **Fragment Preservation:** JSON argument strings arrive in arbitrary fragments across multiple chunks. SafeRoute streams fragments as received without assuming complete JSON per chunk.
- **Index Tracking:** Tool-call indices and IDs are preserved across chunks.
- **Finish Reason:** The terminal chunk yields `finish_reason: "tool_calls"`.
- **Interrupted Streams:** If an upstream provider disconnects mid-stream, an error event is yielded and the stream terminates with `[DONE]`. No falsified complete tool call is ever generated.

---

## 6. Tool-Call and Tool-Result Lifecycle

The complete round-trip interaction between the client and SafeRoute follows a three-step cycle:

1. **Client Request with Tools:**
   Client invokes SafeRoute specifying available tools.
2. **Gateway Response (Model Requests Tool):**
   SafeRoute returns `finish_reason: "tool_calls"` with `tool_calls: [{"id": "call_1", "function": {"name": "search", "arguments": "{\"query\":\"docs\"}"}}]`.
3. **Client Execution & Follow-Up:**
   The client executes the tool in its own environment and passes the result back to SafeRoute:

```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    {"role": "user", "content": "Search for documentation on SafeRoute."},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_1",
          "type": "function",
          "function": {
            "name": "search",
            "arguments": "{\"query\":\"docs\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_1",
      "content": "Found 3 matching articles for SafeRoute."
    }
  ]
}
```

SafeRoute validates the `tool_call_id` linkage, translates the message history into provider-native format, and returns the assistant's final text summary.

---

## 7. Failover and Caching Behavior

### Failover Safety
- **Tool Capability Enforcement:** When failover is enabled (`FAILOVER_ENABLED=true` or `X-Allow-Failover: true`), SafeRoute's fallback model selector inspects whether the candidate fallback model supports tools (`model_supports_tools(candidate)`).
- **Incompatible Models Rejected:** Models without tool support (e.g. `phi3` or mock error variants) are strictly bypassed. SafeRoute will never silently switch to a model that cannot fulfill the requested tool contract.
- **Mid-Stream Failover Prohibited:** As established in Phase 9.2, once streaming output has commenced, failover is disabled to prevent mixing fragments from different providers.

### Cache Isolation
- **Deterministic Key Composition:** The cache key incorporates:
  - Canonicalized messages (including `role`, `tool_call_id`, and `tool_calls`).
  - Canonicalized `tools` definition (sorted by tool name).
  - Canonicalized `tool_choice`.
- **No Cross-Talk:** Requests with different tool definitions or differing `tool_choice` policies generate distinct SHA-256 cache keys.
- **Incomplete Calls:** Unfinished or interrupted tool calls are never cached.

---

## 8. Usage, Pricing, and Persistence

- **Accurate Accounting:** Actual provider-reported token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) is recorded.
- **Pricing Application:** Gateway pricing models calculate cost based on input/output tokens according to the model pricing catalog.
- **Audit Persistence:** Every request (text or tool-calling) is persisted to SQLite with the serving model, status code, latency, and cost metadata.

---

## 9. Security, Validation, and Redaction

- **Input Guardrails:** Regex and heuristic filters inspect both text `content` and assistant `tool_calls` arguments.
- **Output Guardrails:** Generated arguments are inspected before transmission to prevent model exfiltration.
- **Log Privacy:** Tool arguments and headers are redacted from debug and operational logs to protect sensitive user parameters and API tokens.

---

## 10. Test Strategy & Verification Results

### Test Coverage
- `tests/unit/test_tools.py`: 13 tests covering schema limits, duplicate tool rejection, schema size limits, named tool choices, role="tool" validation, model capability mapping, Mock provider determinism, Ollama phi3 rejection, Claude tool normalization, and Gemini function call normalization.
- `tests/integration/test_tools_integration.py`: 11 tests covering end-to-end completions, execution boundary non-execution, tool result follow-ups, streaming fragment chunks, interrupted streams, failover tool compatibility, cache isolation, usage and cost recording, concurrent request safety, and log privacy.

### Test Execution Commands & Results
```bash
pytest tests/unit/test_tools.py tests/integration/test_tools_integration.py -v
============================= 24 passed in 2.11s =============================

pytest -q
306 passed, 1 warning in 20.33s

python scripts/run_evaluation.py --mode quick
==================================================
  SafeRoute Evaluation Suite (Phase 8.4)
==================================================
Total Tests:     15
Passed:          14
Failed:          0
Skipped:         1 (live-only test)
Pass Rate:       100.0%
```

---

## 11. Known Limitations & Next Phase Readiness

1. **Provider Differences in Nested Types:** Gemini function calling has strict constraints on OpenAPI schema constructs (e.g., `anyOf`, `oneOf`). SafeRoute translates standard object/array schemas cleanly; highly complex nested union types should be validated in provider staging.
2. **Live Provider Verification:** Automated test suites use deterministic mock servers and mocked HTTP transports. Live validation against paid Anthropic and Google endpoints should be performed in staging with actual credentials.
3. **Readiness:** SafeRoute LLM Gateway Phase 9.3 is complete, fully tested, and ready for review.
