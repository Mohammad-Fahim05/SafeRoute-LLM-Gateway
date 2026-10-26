from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
import asyncio
import json
import time
import uuid

from app.api.schemas import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionChunkDeltaFunctionCall,
    ChatCompletionChunkDeltaToolCall,
    ChatCompletionNamedToolChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    UsageInfo,
)
from app.core.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderRateLimitError,
)
from app.providers.base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    """In-memory mock provider for deterministic testing without external API calls or costs."""

    def __init__(self, default_response: Optional[str] = None) -> None:
        self._default_response = (
            default_response
            or "This is a deterministic response from the SafeRoute mock provider."
        )
        self.call_count: int = 0
        self._custom_failures: Dict[str, List[Exception]] = {}
        self._custom_stream_failures: Dict[str, List[Tuple[int, Exception]]] = {}

    def reset_call_count(self) -> None:
        """Reset the internal invocation counter to zero."""
        self.call_count = 0

    def set_failure_for_model(self, model: str, error: Exception, times: int = 1) -> None:
        """Configure mock provider to raise error for model for the next `times` invocations."""
        if model not in self._custom_failures:
            self._custom_failures[model] = []
        for _ in range(times):
            self._custom_failures[model].append(error)

    def set_stream_failure_after_chunks(
        self, model: str, error: Exception, chunk_count: int = 1
    ) -> None:
        """Configure mock provider to yield chunk_count chunks and then raise error."""
        if model not in self._custom_stream_failures:
            self._custom_stream_failures[model] = []
        self._custom_stream_failures[model].append((chunk_count, error))

    def reset_custom_behaviors(self) -> None:
        """Clear all configured programmatic failure simulations."""
        self._custom_failures.clear()
        self._custom_stream_failures.clear()

    @property
    def name(self) -> str:
        return "mock"

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Simulate LLM completion based on model configuration and test scenarios."""
        self.call_count += 1

        # Check programmatic custom failure first
        if request.model in self._custom_failures and self._custom_failures[request.model]:
            exc = self._custom_failures[request.model].pop(0)
            raise exc

        # 1. Simulate upstream timeout
        if request.model == "mock-timeout":
            # Sleep longer than gateway timeout to trigger gateway-level timeout handling
            await asyncio.sleep(10.0)
            return self._build_response(request, "This should not be returned due to timeout.")

        # 2. Simulate upstream provider error (500)
        if request.model in ("mock-error", "mock-server-error"):
            raise ProviderError("Simulated upstream provider 500 internal error.")

        # 3. Simulate upstream malformed response
        if request.model == "mock-malformed":
            raise ProviderMalformedResponseError(
                "Upstream provider returned an unparseable or corrupted payload structure."
            )

        # 4. Simulate upstream rate limit (429)
        if request.model == "mock-rate-limit":
            raise ProviderRateLimitError(
                "Simulated upstream 429 rate limit exceeded.", retry_after=0.1
            )

        # 5. Simulate upstream authentication error (401/403)
        if request.model == "mock-auth-error":
            raise ProviderAuthenticationError("Simulated upstream 401 unauthorized.")

        # 6. Tool-calling simulations
        if request.tools and request.tool_choice != "none":
            return self._build_tool_call_response(request)

        # 7. Standard deterministic completion
        response_text = self._default_response
        return self._build_response(request, response_text)

    def _build_tool_call_response(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Construct deterministic tool call response."""
        from app.api.schemas import (
            ChatCompletionNamedToolChoice,
            ChatCompletionMessageToolCall,
            FunctionCall,
        )
        import json

        assert request.tools is not None and len(request.tools) > 0

        # Check for malformed arguments simulation
        if request.model == "mock-tool-call-malformed-args":
            tool_call = ChatCompletionMessageToolCall(
                id="call_mock_malformed",
                type="function",
                function=FunctionCall(
                    name=request.tools[0].function.name,
                    arguments='{"location": "London", "days": ',  # Malformed JSON
                ),
            )
            tool_calls = [tool_call]
        elif request.model == "mock-tool-call-multiple":
            # Simulate 2 distinct tool calls
            tool_calls = [
                ChatCompletionMessageToolCall(
                    id="call_mock_multi_1",
                    type="function",
                    function=FunctionCall(
                        name=request.tools[0].function.name,
                        arguments=json.dumps({"location": "London"}),
                    ),
                ),
                ChatCompletionMessageToolCall(
                    id="call_mock_multi_2",
                    type="function",
                    function=FunctionCall(
                        name=request.tools[min(1, len(request.tools) - 1)].function.name,
                        arguments=json.dumps({"location": "Paris"}),
                    ),
                ),
            ]
        else:
            if isinstance(request.tool_choice, ChatCompletionNamedToolChoice):
                func_name = request.tool_choice.function.name
            else:
                func_name = request.tools[0].function.name

            # Generate arguments matching parameter schema if possible
            args_dict: Dict[str, Any] = {}
            target_tool = next((t for t in request.tools if t.function.name == func_name), request.tools[0])
            if target_tool.function.parameters and "properties" in target_tool.function.parameters:
                for prop, prop_spec in target_tool.function.parameters["properties"].items():
                    t = prop_spec.get("type", "string") if isinstance(prop_spec, dict) else "string"
                    if t in ("integer", "number"):
                        args_dict[prop] = 42
                    elif t == "boolean":
                        args_dict[prop] = True
                    else:
                        args_dict[prop] = "test-value"
            if not args_dict:
                args_dict = {"location": "San Francisco"}

            tool_calls = [
                ChatCompletionMessageToolCall(
                    id="call_mock_det_1",
                    type="function",
                    function=FunctionCall(
                        name=func_name,
                        arguments=json.dumps(args_dict),
                    ),
                )
            ]

        total_prompt_chars = sum(len(m.content or "") for m in request.messages)
        prompt_tokens = max(1, total_prompt_chars // 4)
        completion_tokens = max(1, sum(len(tc.function.arguments) for tc in tool_calls) // 4)
        total_tokens = prompt_tokens + completion_tokens

        return ChatCompletionResponse(
            id=f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
            object="chat.completion",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatChoiceMessage(
                        role="assistant",
                        content=None,
                        tool_calls=tool_calls,
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                is_mock_estimate=True,
                usage_source="mock_estimated",
            ),
        )

    def _build_response(
        self, request: ChatCompletionRequest, content: str
    ) -> ChatCompletionResponse:
        total_prompt_chars = sum(len(m.content or "") for m in request.messages)
        prompt_tokens = max(1, total_prompt_chars // 4)
        finish_reason = "stop"
        if request.max_completion_tokens is not None and len(content) > request.max_completion_tokens * 4:
            content = content[: request.max_completion_tokens * 4]
            completion_tokens = request.max_completion_tokens
            finish_reason = "length"
        else:
            completion_tokens = max(1, len(content) // 4)
        total_tokens = prompt_tokens + completion_tokens

        return ChatCompletionResponse(
            id=f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
            object="chat.completion",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatChoiceMessage(
                        role="assistant",
                        content=content,
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                is_mock_estimate=True,
                usage_source="mock_estimated",
            ),
        )

    async def stream_complete(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Simulate LLM streaming chunk emissions based on model configuration."""
        self.call_count += 1

        # Check custom failure before first chunk
        if request.model in self._custom_failures and self._custom_failures[request.model]:
            exc = self._custom_failures[request.model].pop(0)
            raise exc

        # 1. Simulate upstream timeout
        if request.model == "mock-timeout":
            await asyncio.sleep(10.0)
            yield ChatCompletionChunk(
                id=f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(role="assistant", content="Timeout content"),
                        finish_reason="stop",
                    )
                ],
            )
            return

        # 2. Simulate upstream provider error (500)
        if request.model in ("mock-error", "mock-server-error"):
            raise ProviderError("Simulated upstream provider 500 internal error.")

        # 3. Simulate upstream malformed response
        if request.model == "mock-malformed":
            raise ProviderMalformedResponseError(
                "Upstream provider returned an unparseable or corrupted payload structure."
            )

        # 4. Simulate upstream rate limit (429)
        if request.model == "mock-rate-limit":
            raise ProviderRateLimitError(
                "Simulated upstream 429 rate limit exceeded.", retry_after=0.1
            )

        # 5. Simulate upstream authentication error (401/403)
        if request.model == "mock-auth-error":
            raise ProviderAuthenticationError("Simulated upstream 401 unauthorized.")

        stream_id = f"chatcmpl-mock-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        # Check for configured mid-stream failure
        mid_stream_fail: Optional[Tuple[int, Exception]] = None
        if request.model in self._custom_stream_failures and self._custom_stream_failures[request.model]:
            mid_stream_fail = self._custom_stream_failures[request.model].pop(0)
        elif request.model in ("mock-stream-error-after-chunk", "mock-stream-tool-call-error-after-chunk"):
            mid_stream_fail = (1, ProviderError("Simulated mid-stream provider failure after initial chunks."))

        total_prompt_chars = sum(len(m.content or "") for m in request.messages)
        prompt_tokens = max(1, total_prompt_chars // 4)

        # 6. Streaming tool calls if requested
        if request.tools and request.tool_choice != "none":
            emitted_chunks = 0
            if request.model == "mock-tool-call-multiple":
                # Multi-tool streaming
                # Chunk 1: Tool 0 declaration
                if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                    raise mid_stream_fail[1]
                yield ChatCompletionChunk(
                    id=stream_id,
                    created=created_ts,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(
                                role="assistant",
                                tool_calls=[
                                    ChatCompletionChunkDeltaToolCall(
                                        index=0,
                                        id="call_mock_multi_1",
                                        type="function",
                                        function=ChatCompletionChunkDeltaFunctionCall(
                                            name=request.tools[0].function.name,
                                            arguments="",
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ],
                )
                emitted_chunks += 1
                await asyncio.sleep(0.001)

                # Chunk 2: Tool 0 arguments
                if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                    raise mid_stream_fail[1]
                yield ChatCompletionChunk(
                    id=stream_id,
                    created=created_ts,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(
                                tool_calls=[
                                    ChatCompletionChunkDeltaToolCall(
                                        index=0,
                                        function=ChatCompletionChunkDeltaFunctionCall(
                                            arguments=json.dumps({"location": "London"}),
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ],
                )
                emitted_chunks += 1
                await asyncio.sleep(0.001)

                # Chunk 3: Tool 1 declaration
                tool_1_name = request.tools[min(1, len(request.tools) - 1)].function.name
                if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                    raise mid_stream_fail[1]
                yield ChatCompletionChunk(
                    id=stream_id,
                    created=created_ts,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(
                                tool_calls=[
                                    ChatCompletionChunkDeltaToolCall(
                                        index=1,
                                        id="call_mock_multi_2",
                                        type="function",
                                        function=ChatCompletionChunkDeltaFunctionCall(
                                            name=tool_1_name,
                                            arguments="",
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ],
                )
                emitted_chunks += 1
                await asyncio.sleep(0.001)

                # Chunk 4: Tool 1 arguments
                if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                    raise mid_stream_fail[1]
                yield ChatCompletionChunk(
                    id=stream_id,
                    created=created_ts,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(
                                tool_calls=[
                                    ChatCompletionChunkDeltaToolCall(
                                        index=1,
                                        function=ChatCompletionChunkDeltaFunctionCall(
                                            arguments=json.dumps({"location": "Paris"}),
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ],
                )
                emitted_chunks += 1
                await asyncio.sleep(0.001)

            else:
                # Single tool call streaming
                if isinstance(request.tool_choice, ChatCompletionNamedToolChoice):
                    func_name = request.tool_choice.function.name
                else:
                    func_name = request.tools[0].function.name

                if request.model == "mock-tool-call-malformed-args":
                    arg_chunks = ['{"location": "London", ', '"days": ']
                else:
                    arg_chunks = ['{"location": ', '"San Francisco"}']

                # Chunk 1: Tool call declaration with name
                if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                    raise mid_stream_fail[1]
                yield ChatCompletionChunk(
                    id=stream_id,
                    created=created_ts,
                    model=request.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(
                                role="assistant",
                                tool_calls=[
                                    ChatCompletionChunkDeltaToolCall(
                                        index=0,
                                        id="call_mock_stream_1",
                                        type="function",
                                        function=ChatCompletionChunkDeltaFunctionCall(
                                            name=func_name,
                                            arguments="",
                                        ),
                                    )
                                ],
                            ),
                            finish_reason=None,
                        )
                    ],
                )
                emitted_chunks += 1
                await asyncio.sleep(0.001)

                # Chunks 2 & 3: Argument fragments
                for arg_fragment in arg_chunks:
                    if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                        raise mid_stream_fail[1]
                    yield ChatCompletionChunk(
                        id=stream_id,
                        created=created_ts,
                        model=request.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(
                                    tool_calls=[
                                        ChatCompletionChunkDeltaToolCall(
                                            index=0,
                                            function=ChatCompletionChunkDeltaFunctionCall(
                                                arguments=arg_fragment,
                                            ),
                                        )
                                    ],
                                ),
                                finish_reason=None,
                            )
                        ],
                    )
                    emitted_chunks += 1
                    await asyncio.sleep(0.001)

            if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                raise mid_stream_fail[1]

            # Terminal tool-call chunk with finish_reason="tool_calls"
            completion_tokens = 12
            yield ChatCompletionChunk(
                id=stream_id,
                created=created_ts,
                model=request.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(),
                        finish_reason="tool_calls",
                    )
                ],
                usage=UsageInfo(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    is_mock_estimate=True,
                    usage_source="mock_estimated",
                ),
            )
            return

        # 7. Response text generation & chunking
        if request.model == "mock-empty-response":
            words: List[str] = []
        elif request.model == "mock-short-response":
            words = ["Hello!"]
        else:
            response_text = self._default_response
            # Deterministic word-boundary chunking
            raw_words = response_text.split(" ")
            words = [f"{w} " if i < len(raw_words) - 1 else w for i, w in enumerate(raw_words)]

        total_completion_chars = sum(len(w) for w in words)
        completion_tokens = max(1, total_completion_chars // 4) if words else 0
        total_tokens = prompt_tokens + completion_tokens

        usage_info = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_mock_estimate=True,
            usage_source="mock_estimated",
        )

        emitted_chunks = 0
        if not words:
            # Empty completion: single terminal chunk
            yield ChatCompletionChunk(
                id=stream_id,
                created=created_ts,
                model=request.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(role="assistant", content=""),
                        finish_reason="stop",
                    )
                ],
                usage=usage_info,
            )
            return

        for idx, word in enumerate(words):
            if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
                raise mid_stream_fail[1]

            role_val = "assistant" if idx == 0 else None
            yield ChatCompletionChunk(
                id=stream_id,
                created=created_ts,
                model=request.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(role=role_val, content=word),
                        finish_reason=None,
                    )
                ],
            )
            emitted_chunks += 1
            await asyncio.sleep(0.001)

        if mid_stream_fail is not None and emitted_chunks >= mid_stream_fail[0]:
            raise mid_stream_fail[1]

        # Final terminal chunk with finish_reason="stop" and usage
        yield ChatCompletionChunk(
            id=stream_id,
            created=created_ts,
            model=request.model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content=""),
                    finish_reason="stop",
                )
            ],
            usage=usage_info,
        )

    async def check_health(self) -> bool:
        """Mock provider is always available in-memory."""
        return True
