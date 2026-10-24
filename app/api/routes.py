"""FastAPI route handlers for health, readiness, and chat completions."""

import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.config import Settings, get_settings
from app.core.errors import (
    AppException,
    InvalidModelError,
    ProviderTimeoutError,
)
from app.core.logging import logger
from app.core.request_context import get_request_id
from app.providers import get_all_providers, get_provider_for_model

router = APIRouter()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check(settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    """Liveness probe returning basic service operational status."""
    return {
        "status": "ok",
        "app": "SafeRoute LLM Gateway",
        "environment": settings.app_env,
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check() -> JSONResponse:
    """Readiness probe verifying that backend dependencies/providers are accessible."""
    providers = get_all_providers()
    provider_statuses = {}
    is_ready = True

    for name, provider in providers.items():
        try:
            available = await provider.check_health()
            provider_statuses[name] = "available" if available else "unavailable"
            if not available:
                is_ready = False
        except Exception as exc:
            logger.error(f"Provider {name} health check failed: {exc}")
            provider_statuses[name] = "error"
            is_ready = False

    if is_ready:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ready", "providers": provider_statuses},
        )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "not_ready", "providers": provider_statuses},
    )


@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionResponse,
    status_code=status.HTTP_200_OK,
)
async def chat_completions(
    request: ChatCompletionRequest,
    settings: Settings = Depends(get_settings),
) -> ChatCompletionResponse:
    """Process OpenAI-compatible chat completion requests."""
    rid = get_request_id()

    # 1. Model allowlist verification
    if request.model not in settings.allowed_models:
        logger.warning(
            f"Rejected request for unauthorized model: {request.model}",
            extra={"extra_data": {"model": request.model}},
        )
        raise InvalidModelError(
            f"The model '{request.model}' is not permitted or supported. Allowed models: {', '.join(settings.allowed_models)}"
        )

    # 2. Safety limits verification
    if len(request.messages) > settings.max_messages_per_request:
        raise AppException(
            f"Message count ({len(request.messages)}) exceeds maximum allowed ({settings.max_messages_per_request}).",
            status_code=400,
            error_code="message_limit_exceeded",
        )

    if (
        request.max_completion_tokens is not None
        and request.max_completion_tokens > settings.max_completion_tokens_limit
    ):
        raise AppException(
            f"max_completion_tokens ({request.max_completion_tokens}) exceeds system limit of {settings.max_completion_tokens_limit}.",
            status_code=422,
            error_code="validation_error",
        )

    # Safe structured log (never logging prompt content or personal data)
    logger.info(
        "Processing chat completion request",
        extra={
            "extra_data": {
                "model": request.model,
                "message_count": len(request.messages),
                "temperature": request.temperature,
                "max_tokens": request.max_completion_tokens,
            }
        },
    )

    # 3. Resolve provider
    provider = get_provider_for_model(request.model)

    # 4. Invoke provider with controlled gateway timeout
    try:
        response = await asyncio.wait_for(
            provider.complete(request),
            timeout=settings.provider_timeout_seconds,
        )
        return response
    except asyncio.TimeoutError:
        logger.warning(
            f"Provider '{provider.name}' timed out after {settings.provider_timeout_seconds}s"
        )
        raise ProviderTimeoutError(
            f"Upstream provider timed out after {settings.provider_timeout_seconds} seconds."
        )
