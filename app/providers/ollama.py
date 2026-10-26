import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx

from app.api.schemas import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionChunkDeltaFunctionCall,
    ChatCompletionChunkDeltaToolCall,
    ChatCompletionMessageToolCall,
    ChatCompletionRequest,
    ChatCompletionResponse,
    FunctionCall,
    UsageInfo,
)
from app.core.errors import (
    InvalidModelError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderTimeoutError,
    UnsupportedParameterError,
)
from app.core.logging import logger
from app.providers.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """Adapter for local Ollama instances implementing the BaseLLMProvider interface."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 30.0,
        http_client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Any] = None,
    ) -> None:
        if settings is not None:
            base_url = getattr(settings, "ollama_base_url", base_url)
            timeout = getattr(settings, "provider_timeout_seconds", timeout)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._external_client = http_client is not None
        self._client: Optional[httpx.AsyncClient] = http_client

    @property
    def name(self) -> str:
        return "ollama"

    async def get_client(self) -> httpx.AsyncClient:
        """Get or lazily initialize the reusable asynchronous HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=5.0),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the managed HTTP client connection pool on application shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def check_health(self) -> bool:
        """Verify reachability of the Ollama service."""
        try:
            client = await self.get_client()
            response = await client.get("/api/version", timeout=3.0)
            return response.status_code == 200
        except Exception as exc:
            logger.debug(f"Ollama health check probe failed: {exc}")
            return False

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Submit a validated chat completion request to the Ollama /api/chat endpoint."""
        client = await self.get_client()

        # Validate tool capability for model if tools requested
        if request.tools and request.tool_choice != "none":
            if not self.supports_tools(request.model):
                raise UnsupportedParameterError(
                    f"Model '{request.model}' does not support tool calling in Ollama adapter."
                )

        # 1. Map gateway request to Ollama request payload
        ollama_messages: List[Dict[str, Any]] = []
        for msg in request.messages:
            m: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                m["tool_calls"] = [tc.model_dump(exclude_none=True) for tc in msg.tool_calls]
            ollama_messages.append(m)

        options: Dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_completion_tokens is not None:
            options["num_predict"] = request.max_completion_tokens

        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": ollama_messages,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if request.tools and request.tool_choice != "none":
            payload["tools"] = [t.model_dump(exclude_none=True) for t in request.tools]

        # 2. Transmit request with controlled error handling
        url = "/api/chat"
        try:
            response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            logger.error(f"Cannot connect to Ollama at {self.base_url}: {exc}")
            raise ProviderError("Upstream Ollama service is unreachable or not running.")
        except httpx.TimeoutException as exc:
            logger.warning(f"Ollama call timed out after {self.timeout}s: {exc}")
            raise ProviderTimeoutError(f"Upstream Ollama service timed out after {self.timeout} seconds.")
        except Exception as exc:
            logger.error(f"Unexpected connection error calling Ollama: {exc}")
            raise ProviderError(f"Network error communicating with Ollama: {str(exc)}")

        # 3. Handle HTTP status codes
        if response.status_code == 404:
            logger.warning(f"Requested model '{request.model}' was not found in Ollama.")
            raise InvalidModelError(
                f"Model '{request.model}' was not found in the local Ollama instance."
            )

        if response.status_code >= 400:
            error_msg = response.text[:200]
            logger.error(f"Ollama returned HTTP error {response.status_code}: {error_msg}")
            raise ProviderError(f"Upstream Ollama service returned HTTP {response.status_code}.")

        # 4. Parse response JSON
        try:
            data = response.json()
        except Exception as exc:
            logger.error(f"Failed to parse JSON response from Ollama: {exc}")
            raise ProviderMalformedResponseError("Ollama returned an unparseable JSON payload.")

        # 5. Extract and normalize content
        message_data = data.get("message")
        if not isinstance(message_data, dict) or (
            "content" not in message_data and "tool_calls" not in message_data
        ):
            logger.error(f"Ollama response missing message or content: {data}")
            raise ProviderMalformedResponseError(
                "Ollama returned a malformed response missing message content."
            )

        content = message_data.get("content") or ""
        tool_calls: List[ChatCompletionMessageToolCall] = []
        if "tool_calls" in message_data and isinstance(message_data["tool_calls"], list):
            for tc in message_data["tool_calls"]:
                fn_info = tc.get("function", {})
                raw_args = fn_info.get("arguments", {})
                args_str = json.dumps(raw_args) if isinstance(raw_args, (dict, list)) else str(raw_args)
                tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        type="function",
                        function=FunctionCall(
                            name=fn_info.get("name", ""),
                            arguments=args_str,
                        ),
                    )
                )

        if tool_calls:
            finish_reason = "tool_calls"
            content_val = content if content else None
        else:
            finish_reason = data.get("done_reason") or "stop"
            content_val = content

        # 6. Extract token usage if provided
        prompt_eval_count = data.get("prompt_eval_count")
        eval_count = data.get("eval_count")

        prompt_tokens: Optional[int] = int(prompt_eval_count) if prompt_eval_count is not None else None
        completion_tokens: Optional[int] = int(eval_count) if eval_count is not None else None

        if prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens
            usage_source = "provider_reported"
        elif prompt_tokens is not None or completion_tokens is not None:
            total_tokens = None
            usage_source = "provider_reported"
        else:
            total_tokens = None
            usage_source = "unavailable"

        return ChatCompletionResponse(
            id=f"chatcmpl-ollama-{uuid.uuid4().hex[:12]}",
            object="chat.completion",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatChoiceMessage(
                        role="assistant",
                        content=content_val,
                        tool_calls=tool_calls if tool_calls else None,
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                is_mock_estimate=False,
                usage_source=usage_source,
            ),
        )

    async def stream_complete(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Submit a validated chat completion request to the Ollama /api/chat endpoint with streaming."""
        client = await self.get_client()

        # Validate tool capability for model if tools requested
        if request.tools and request.tool_choice != "none":
            if not self.supports_tools(request.model):
                raise UnsupportedParameterError(
                    f"Model '{request.model}' does not support tool calling in Ollama adapter."
                )

        ollama_messages: List[Dict[str, Any]] = []
        for msg in request.messages:
            m: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                m["tool_calls"] = [tc.model_dump(exclude_none=True) for tc in msg.tool_calls]
            ollama_messages.append(m)

        options: Dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_completion_tokens is not None:
            options["num_predict"] = request.max_completion_tokens

        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": ollama_messages,
            "stream": True,
        }
        if options:
            payload["options"] = options
        if request.tools and request.tool_choice != "none":
            payload["tools"] = [t.model_dump(exclude_none=True) for t in request.tools]

        url = "/api/chat"
        created_ts = int(time.time())

        try:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code >= 400:
                    raw_bytes = await response.aread()
                    error_preview = raw_bytes.decode("utf-8", errors="replace")[:200]
                    logger.error(f"Ollama returned HTTP error {response.status_code} on stream: {error_preview}")
                    raise ProviderError(f"Upstream Ollama service returned HTTP {response.status_code}.")

                stream_id = f"chatcmpl-ollama-{uuid.uuid4().hex[:12]}"
                serving_model = request.model
                prompt_tokens: Optional[int] = None
                completion_tokens: Optional[int] = None
                total_tokens: Optional[int] = None
                finish_reason = "stop"
                first_chunk = True
                had_tool_call = False

                async for line in response.aiter_lines():
                    clean_line = line.strip()
                    if not clean_line:
                        continue

                    try:
                        data = json.loads(clean_line)
                    except Exception:
                        continue

                    serving_model = data.get("model", serving_model)
                    msg_data = data.get("message", {})
                    content_chunk = msg_data.get("content", "")
                    tc_deltas: List[ChatCompletionChunkDeltaToolCall] = []

                    if "tool_calls" in msg_data and isinstance(msg_data["tool_calls"], list):
                        for tc in msg_data["tool_calls"]:
                            fn_info = tc.get("function", {})
                            raw_args = fn_info.get("arguments", {})
                            args_str = json.dumps(raw_args) if isinstance(raw_args, (dict, list)) else str(raw_args)
                            tc_deltas.append(
                                ChatCompletionChunkDeltaToolCall(
                                    index=len(tc_deltas),
                                    id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                                    type="function",
                                    function=ChatCompletionChunkDeltaFunctionCall(
                                        name=fn_info.get("name", ""),
                                        arguments=args_str,
                                    ),
                                )
                            )

                    if content_chunk or tc_deltas or first_chunk:
                        role_val = "assistant" if first_chunk else None
                        yield ChatCompletionChunk(
                            id=stream_id,
                            created=created_ts,
                            model=serving_model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta=ChatCompletionChunkDelta(
                                        role=role_val,
                                        content=content_chunk if content_chunk else None,
                                        tool_calls=tc_deltas if tc_deltas else None,
                                    ),
                                    finish_reason=None,
                                )
                            ],
                        )
                        first_chunk = False
                        if tc_deltas:
                            had_tool_call = True

                    if data.get("done") is True:
                        prompt_eval = data.get("prompt_eval_count")
                        eval_count = data.get("eval_count")
                        prompt_tokens = int(prompt_eval) if prompt_eval is not None else None
                        completion_tokens = int(eval_count) if eval_count is not None else None
                        if prompt_tokens is not None and completion_tokens is not None:
                            total_tokens = prompt_tokens + completion_tokens
                        elif prompt_tokens is not None or completion_tokens is not None:
                            total_tokens = None
                        finish_reason = "stop"

                # Terminal chunk
                if had_tool_call:
                    finish_reason = "tool_calls"

                usage_source = "provider_reported" if (prompt_tokens is not None or completion_tokens is not None) else "unavailable"
                final_usage = UsageInfo(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    is_mock_estimate=False,
                    usage_source=usage_source,
                )
                yield ChatCompletionChunk(
                    id=stream_id,
                    created=created_ts,
                    model=serving_model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(content=""),
                            finish_reason=finish_reason,
                        )
                    ],
                    usage=final_usage,
                )

        except (ProviderError, ProviderTimeoutError):
            raise
        except httpx.ConnectError as exc:
            logger.error(f"Cannot connect to Ollama stream at {self.base_url}: {exc}")
            raise ProviderError("Upstream Ollama service is unreachable or not running.")
        except httpx.TimeoutException as exc:
            logger.warning(f"Ollama stream timed out after {self.timeout}s: {exc}")
            raise ProviderTimeoutError(f"Upstream Ollama service timed out after {self.timeout} seconds.")
        except Exception as exc:
            logger.error(f"Unexpected error in Ollama stream: {exc}")
            raise ProviderError(f"Error communicating with Ollama stream: {exc}")
