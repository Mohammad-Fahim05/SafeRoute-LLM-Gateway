"""Deterministic, cost-free Mock LLM Provider for testing."""

import asyncio
import time
import uuid
from typing import Optional

from app.api.schemas import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    UsageInfo,
)
from app.core.errors import ProviderError, ProviderMalformedResponseError
from app.providers.base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    """In-memory mock provider for deterministic testing without external API calls or costs."""

    def __init__(self, default_response: Optional[str] = None) -> None:
        self._default_response = (
            default_response
            or "This is a deterministic response from the SafeRoute mock provider."
        )

    @property
    def name(self) -> str:
        return "mock"

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Simulate LLM completion based on model configuration and test scenarios."""
        # 1. Simulate upstream timeout
        if request.model == "mock-timeout":
            # Sleep longer than gateway timeout to trigger gateway-level timeout handling
            await asyncio.sleep(10.0)
            return self._build_response(request, "This should not be returned due to timeout.")

        # 2. Simulate upstream provider error
        if request.model == "mock-error":
            raise ProviderError("Simulated upstream provider 500 internal error.")

        # 3. Simulate upstream malformed response
        if request.model == "mock-malformed":
            raise ProviderMalformedResponseError(
                "Upstream provider returned an unparseable or corrupted payload structure."
            )

        # 4. Standard deterministic completion
        response_text = self._default_response

        # Build response with clearly labeled deterministic mock estimates
        return self._build_response(request, response_text)

    def _build_response(
        self, request: ChatCompletionRequest, content: str
    ) -> ChatCompletionResponse:
        # Calculate deterministic character-based mock token estimates (approx 4 chars per token)
        total_prompt_chars = sum(len(m.content) for m in request.messages)
        prompt_tokens = max(1, total_prompt_chars // 4)
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
                    finish_reason="stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                is_mock_estimate=True,
            ),
        )

    async def check_health(self) -> bool:
        """Mock provider is always available in-memory."""
        return True
