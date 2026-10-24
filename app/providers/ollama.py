"""Ollama LLM Provider adapter using asynchronous HTTP client."""

import time
import uuid
from typing import Any, Dict, Optional
import httpx

from app.api.schemas import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    UsageInfo,
)
from app.core.errors import (
    InvalidModelError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderTimeoutError,
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
    ) -> None:
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

        # 1. Map gateway request to Ollama request payload
        ollama_messages = [
            {"role": msg.role, "content": msg.content} for msg in request.messages
        ]

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
        if not isinstance(message_data, dict) or "content" not in message_data:
            logger.error(f"Ollama response missing message or content: {data}")
            raise ProviderMalformedResponseError(
                "Ollama returned a malformed response missing message content."
            )

        content = message_data.get("content", "")
        finish_reason = data.get("done_reason") or "stop"

        # 6. Extract token usage if provided
        prompt_eval_count = data.get("prompt_eval_count")
        eval_count = data.get("eval_count")

        if prompt_eval_count is not None and eval_count is not None:
            prompt_tokens = int(prompt_eval_count)
            completion_tokens = int(eval_count)
            total_tokens = prompt_tokens + completion_tokens
            is_mock = False
        else:
            # Token usage not supplied by Ollama
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            is_mock = False

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
                        content=content,
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                is_mock_estimate=is_mock,
            ),
        )
