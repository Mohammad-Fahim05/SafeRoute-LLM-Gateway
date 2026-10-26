"""FastAPI route handlers for health, readiness, chat completions, usage statistics, and CSV export."""

import asyncio
import json
import time
from typing import Any, Dict, Optional, Union
from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

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
    ChatMessage,
    FunctionCall,
    UsageInfo,
    UsageSummaryResponse,
)
from app.cache import (
    ExactResponseCache,
    SemanticResponseCache,
    build_cache_key,
    get_cache,
    get_semantic_cache,
)
from app.config import Settings, get_settings
from app.core.auth import verify_api_key, verify_metrics_access
from app.core.errors import (
    AppException,
    DatabaseError,
    InputGuardrailBlockedError,
    InvalidModelError,
    OutputGuardrailBlockedError,
    ProviderTimeoutError,
    RateLimitExceededError,
    RateLimiterUnavailableError,
    SafetyClassificationBlockedError,
    SafetyClassifierUnavailableError,
    UnsupportedParameterError,
)
from app.core.logging import logger
from app.core.request_context import get_request_id
from app.db.service import DatabaseService, db_service
from app.db.session import get_engine
from app.guardrails import (
    BaseSafetyClassifier,
    GuardrailEngine,
    get_guardrail_engine,
    get_safety_classifier,
)
from app.limiter import RateLimiter, get_rate_limiter
from app.providers import (
    execute_with_failover,
    get_all_providers,
    get_provider_for_model,
    init_stream_with_failover,
)


router = APIRouter()


async def _safe_record_outcome(
    settings: Settings,
    request_id: str,
    client_id: Optional[str],
    model_requested: str,
    provider: str,
    http_status: int,
    status: str,
    duration_ms: float,
    provider_latency_ms: Optional[float] = None,
    model_actual: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    usage_source: str = "unavailable",
    is_estimate: bool = False,
    cache_status: str = "not_applicable",
    attempts_count: int = 1,
    failover_occurred: bool = False,
    attempt_sequence: Optional[str] = None,
    stream: bool = False,
    stream_status: Optional[str] = None,
) -> None:
    """Helper to record request outcomes safely without dropping user requests if DB is degraded."""
    try:
        db_svc = DatabaseService(engine=get_engine(settings.database_url))
        await asyncio.to_thread(
            db_svc.record_request_outcome,
            request_id=request_id,
            client_id=client_id,
            model_requested=model_requested,
            provider=provider,
            http_status=http_status,
            status=status,
            duration_ms=duration_ms,
            provider_latency_ms=provider_latency_ms,
            model_actual=model_actual,
            error_code=error_code,
            error_message=error_message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_source=usage_source,
            is_estimate=is_estimate,
            cache_status=cache_status,
            attempts_count=attempts_count,
            failover_occurred=failover_occurred,
            attempt_sequence=attempt_sequence,
            stream=stream,
            stream_status=stream_status,
        )
    except Exception as db_exc:
        logger.error(f"Database persistence failure for request {request_id}: {db_exc}", exc_info=True)
        if settings.database_strict_mode:
            raise DatabaseError("Database persistence failed in strict mode.")



@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check(settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    """Liveness probe returning basic service operational status."""
    return {
        "status": "ok",
        "app": "SafeRoute LLM Gateway",
        "environment": settings.app_env,
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check(
    settings: Settings = Depends(get_settings),
    cache_svc: ExactResponseCache = Depends(get_cache),
    limiter_svc: RateLimiter = Depends(get_rate_limiter),
) -> JSONResponse:
    """Readiness probe verifying that backend dependencies, storage, models, and providers are accessible."""
    is_ready = True
    provider_statuses = {}

    # 1. Verify upstream provider adapters
    providers = get_all_providers(settings)
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

    # 2. Verify database connection
    db_status = "available"
    try:
        from app.db.session import get_engine
        from sqlalchemy import text
        engine = get_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error(f"Database readiness check failed: {exc}")
        db_status = "unavailable"
        if getattr(settings, "database_strict_mode", False) or getattr(settings, "app_env", "") in ("production", "prod"):
            is_ready = False

    # 3. Verify Redis connection (if cache or rate limiting is active)
    redis_status = "disabled"
    if settings.cache_enabled or settings.rate_limit_enabled or getattr(settings, "semantic_cache_enabled", False):
        try:
            client = None
            if settings.cache_enabled:
                client = await cache_svc._get_client()
            if client is None and settings.rate_limit_enabled:
                client = await limiter_svc._get_client()
            if client is None and getattr(settings, "semantic_cache_enabled", False):
                from app.cache.semantic_cache import get_semantic_cache
                sem_svc = get_semantic_cache(settings)
                client = await sem_svc._get_client() if hasattr(sem_svc, "_get_client") else getattr(sem_svc, "_client", None)

            if client is not None:
                if hasattr(client, "ping"):
                    await client.ping()
                redis_status = "available"
            else:
                redis_status = "unavailable"
                should_fail_closed = False
                if settings.cache_enabled and getattr(settings, "cache_failure_policy", "fail_open") == "fail_closed":
                    should_fail_closed = True
                if settings.rate_limit_enabled and getattr(settings, "rate_limit_failure_policy", "fail_closed") == "fail_closed":
                    should_fail_closed = True
                if getattr(settings, "semantic_cache_enabled", False) and getattr(settings, "semantic_cache_failure_policy", "fail_open") == "fail_closed":
                    should_fail_closed = True
                if should_fail_closed:
                    is_ready = False
        except Exception as exc:
            logger.warning(f"Redis readiness check failed: {exc}")
            redis_status = "unavailable"
            should_fail_closed = False
            if settings.cache_enabled and getattr(settings, "cache_failure_policy", "fail_open") == "fail_closed":
                should_fail_closed = True
            if settings.rate_limit_enabled and getattr(settings, "rate_limit_failure_policy", "fail_closed") == "fail_closed":
                should_fail_closed = True
            if getattr(settings, "semantic_cache_enabled", False) and getattr(settings, "semantic_cache_failure_policy", "fail_open") == "fail_closed":
                should_fail_closed = True
            if should_fail_closed:
                is_ready = False

    # 4. Verify safety classifier status
    safety_status = "disabled"
    if getattr(settings, "safety_classifier_enabled", False):
        safety_status = "available"
        if getattr(settings, "safety_classifier_provider", "local") == "local":
            clf = get_safety_classifier(settings)
            if hasattr(clf, "_model") and clf._model is None:
                safety_status = "unwarmed"

    content = {
        "status": "ready" if is_ready else "not_ready",
        "database": db_status,
        "redis": redis_status,
        "safety_classifier": safety_status,
        "providers": provider_statuses,
    }

    if is_ready:
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=content)


@router.get("/metrics")
async def prometheus_metrics(
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(verify_metrics_access),
) -> Response:
    """Expose Prometheus metrics for gateway observability and scraping."""
    if not settings.metrics_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Metrics endpoint is disabled.")
    from app.metrics import get_metrics
    from prometheus_client import CONTENT_TYPE_LATEST
    body = get_metrics().export_metrics()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


async def _sse_replay_generator(
    cached_resp: ChatCompletionResponse,
    request_id: str,
    client_id: str,
    request: ChatCompletionRequest,
    provider_name: str,
    route_start: float,
    settings: Settings,
    cache_layer: str,
):
    """Replay a cached ChatCompletionResponse as standard OpenAI-compatible SSE events."""
    stream_outcome = "completed"
    if getattr(settings, "metrics_enabled", True):
        try:
            from app.metrics import get_metrics
            get_metrics().increment_active_streams()
        except Exception:
            pass

    try:
        if cached_resp.choices:
            choice = cached_resp.choices[0]
            choice_content = choice.message.content or ""
            has_tool_calls = bool(choice.message.tool_calls)

            # 1. Role announcement chunk
            chunk_role = ChatCompletionChunk(
                id=f"chatcmpl-{request_id}",
                created=int(time.time()),
                model=cached_resp.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(role="assistant", content=""),
                        finish_reason=None,
                    )
                ],
            )
            yield chunk_role.to_sse_event()

            # 2. Content delta chunks (split into word/whitespace fragments for realistic, standard SSE delivery)
            if choice_content:
                import re
                tokens = re.findall(r"\S+|\s+", choice_content)
                if not tokens:
                    tokens = [choice_content]
                for tok in tokens:
                    chunk_tok = ChatCompletionChunk(
                        id=f"chatcmpl-{request_id}",
                        created=int(time.time()),
                        model=cached_resp.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(content=tok),
                                finish_reason=None,
                            )
                        ],
                    )
                    yield chunk_tok.to_sse_event()

            # 3. Tool call delta chunks (if cached response called tools)
            if has_tool_calls and choice.message.tool_calls:
                for tc_idx, tc in enumerate(choice.message.tool_calls):
                    tc_delta = ChatCompletionChunkDeltaToolCall(
                        index=tc_idx,
                        id=tc.id,
                        type="function",
                        function=ChatCompletionChunkDeltaFunctionCall(
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        ),
                    )
                    chunk_tc = ChatCompletionChunk(
                        id=f"chatcmpl-{request_id}",
                        created=int(time.time()),
                        model=cached_resp.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=ChatCompletionChunkDelta(tool_calls=[tc_delta]),
                                finish_reason=None,
                            )
                        ],
                    )
                    yield chunk_tc.to_sse_event()

            # 4. Terminal choice chunk with finish_reason and usage metadata
            chunk_finish = ChatCompletionChunk(
                id=f"chatcmpl-{request_id}",
                created=int(time.time()),
                model=cached_resp.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(),
                        finish_reason=choice.finish_reason or ("tool_calls" if has_tool_calls else "stop"),
                    )
                ],
                usage=cached_resp.usage,
            )
            yield chunk_finish.to_sse_event()

        # 5. Terminal SSE marker
        yield "data: [DONE]\n\n"

    except asyncio.CancelledError:
        stream_outcome = "cancelled"
        logger.info(f"Replayed streaming request {request_id} was cancelled by client.")
        raise
    except Exception as exc:
        stream_outcome = "failed_post_stream"
        logger.error(f"Error during streaming cache replay {request_id}: {exc}")
        err_payload = json.dumps({
            "error": {
                "message": "Error replaying cached stream.",
                "type": "stream_error",
                "code": "stream_replay_error",
                "request_id": request_id,
            }
        })
        yield f"data: {err_payload}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        if getattr(settings, "metrics_enabled", True):
            try:
                from app.metrics import get_metrics
                get_metrics().decrement_active_streams()
            except Exception:
                pass

        total_duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        record_status = "success" if stream_outcome == "completed" else "failed"
        record_http = 200 if stream_outcome == "completed" else (499 if stream_outcome == "cancelled" else 502)

        input_tok = cached_resp.usage.prompt_tokens if cached_resp.usage else None
        output_tok = cached_resp.usage.completion_tokens if cached_resp.usage else None
        total_tok = cached_resp.usage.total_tokens if cached_resp.usage else None
        is_est = cached_resp.usage.is_mock_estimate if cached_resp.usage else False

        await _safe_record_outcome(
            settings=settings,
            request_id=request_id,
            client_id=client_id,
            model_requested=request.model,
            model_actual=cached_resp.model,
            provider=provider_name,
            http_status=record_http,
            status=record_status,
            duration_ms=total_duration_ms,
            provider_latency_ms=0.0,
            input_tokens=input_tok,
            output_tokens=output_tok,
            total_tokens=total_tok,
            usage_source="cache_hit",
            is_estimate=is_est,
            cache_status="hit",
            stream=True,
            stream_status=stream_outcome,
        )


@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionResponse,
    status_code=status.HTTP_200_OK,
)
async def chat_completions(
    request: ChatCompletionRequest,
    response: Response,
    x_allow_failover: Optional[str] = Header(None, alias="X-Allow-Failover"),
    settings: Settings = Depends(get_settings),
    client_id: str = Depends(verify_api_key),
    cache: ExactResponseCache = Depends(get_cache),
    semantic_cache: SemanticResponseCache = Depends(get_semantic_cache),
    limiter: RateLimiter = Depends(get_rate_limiter),
    guardrails: GuardrailEngine = Depends(get_guardrail_engine),
    safety_classifier: BaseSafetyClassifier = Depends(get_safety_classifier),
) -> Union[ChatCompletionResponse, Response]:
    """Process OpenAI-compatible chat completion requests and durably record outcomes."""
    rid = get_request_id()
    route_start = time.perf_counter()
    provider_latency_ms: Optional[float] = None
    provider_name = "unknown"

    # Determine effective failover policy for this request
    # Precedence: Header (X-Allow-Failover) > Request Body (allow_failover) > Global (Settings.failover_enabled)
    effective_allow_failover = settings.failover_enabled
    if request.allow_failover is not None:
        effective_allow_failover = request.allow_failover
    if x_allow_failover is not None:
        clean_hdr = x_allow_failover.strip().lower()
        if clean_hdr in ("true", "1", "yes", "enabled"):
            effective_allow_failover = True
        elif clean_hdr in ("false", "0", "no", "disabled"):
            effective_allow_failover = False
        else:
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = (
                f"Invalid value for X-Allow-Failover header: '{x_allow_failover}'. "
                "Must be a boolean value ('true' or 'false')."
            )
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="invalid_request",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise AppException(
                err_msg,
                status_code=400,
                error_code="invalid_request",
            )

    # 1. Model allowlist verification
    if request.model not in settings.allowed_models:
        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        err_msg = f"The model '{request.model}' is not permitted or supported. Allowed models: {', '.join(settings.allowed_models)}"
        logger.warning(
            f"Rejected request for unauthorized model: {request.model}",
            extra={"extra_data": {"model": request.model, "client_id": client_id}},
        )
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            provider="gateway",
            http_status=400,
            status="failed",
            duration_ms=duration_ms,
            error_code="invalid_model",
            error_message=err_msg,
            cache_status="not_applicable",
        )
        raise InvalidModelError(err_msg)

    # 1.05 Model lifecycle status & adapter verification (Phase 9.3.2)
    from app.pricing.calculator import pricing_engine
    model_meta = pricing_engine.models.get(request.model)
    if model_meta:
        m_status = str(model_meta.get("status", "active")).lower().strip()
        if m_status in ("retired", "deprecated") and not getattr(settings, "allow_retired_models", False) and settings.app_env != "test":
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"The model '{request.model}' is retired or deprecated and cannot be selected for new requests."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="invalid_model",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise InvalidModelError(err_msg)

        if m_status == "reference_unsupported":
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"The model '{request.model}' is an external reference catalog entry and has no implemented provider adapter in SafeRoute."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="invalid_model",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise InvalidModelError(err_msg)

        if m_status == "restricted_legacy" and not getattr(settings, "allow_restricted_models", False):
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"The model '{request.model}' is a restricted legacy model and is not permitted under current policy. Set ALLOW_RESTRICTED_MODELS=true to permit access."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="invalid_model",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise InvalidModelError(err_msg)

    # 1.1 Tool calling support verification for requested model
    has_tools = bool(request.tools and request.tool_choice != "none")
    if has_tools:
        from app.providers.base import model_supports_tools
        if not model_supports_tools(request.model):
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"The requested model '{request.model}' does not support tools/function calling."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="unsupported_parameter",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise UnsupportedParameterError(err_msg)

    # 1.2 Streaming support verification for requested model
    if request.stream:
        from app.providers.base import model_supports_streaming, model_supports_streaming_tools
        if not model_supports_streaming(request.model):
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"The requested model '{request.model}' does not support streaming."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="unsupported_parameter",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise UnsupportedParameterError(err_msg)

        if has_tools and not model_supports_streaming_tools(request.model):
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"The requested model '{request.model}' does not support streaming tool calling."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="unsupported_parameter",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise UnsupportedParameterError(err_msg)

    # 2. Safety limits verification
    if len(request.messages) > settings.max_messages_per_request:
        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        err_msg = f"Message count ({len(request.messages)}) exceeds maximum allowed ({settings.max_messages_per_request})."
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            provider="gateway",
            http_status=400,
            status="failed",
            duration_ms=duration_ms,
            error_code="message_limit_exceeded",
            error_message=err_msg,
            cache_status="not_applicable",
        )
        raise AppException(
            err_msg,
            status_code=400,
            error_code="message_limit_exceeded",
        )

    if (
        request.max_completion_tokens is not None
        and request.max_completion_tokens > settings.max_completion_tokens_limit
    ):
        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        err_msg = f"max_completion_tokens ({request.max_completion_tokens}) exceeds system limit of {settings.max_completion_tokens_limit}."
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            provider="gateway",
            http_status=422,
            status="failed",
            duration_ms=duration_ms,
            error_code="validation_error",
            error_message=err_msg,
            cache_status="not_applicable",
        )
        raise AppException(
            err_msg,
            status_code=422,
            error_code="validation_error",
        )

    # 3. Client Rate Limiting (enforced after schema/model validation, before provider/cache)
    try:
        rate_res = await limiter.check_rate_limit(client_id)
    except RateLimiterUnavailableError as exc:
        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            provider="gateway",
            http_status=503,
            status="failed",
            duration_ms=duration_ms,
            error_code="rate_limiter_unavailable",
            error_message=exc.message,
            cache_status="not_applicable",
        )
        raise

    if settings.rate_limit_enabled and rate_res.status in ("ok", "exceeded"):
        response.headers["X-RateLimit-Limit"] = str(rate_res.limit)
        response.headers["X-RateLimit-Remaining"] = str(rate_res.remaining)
        response.headers["X-RateLimit-Reset"] = str(rate_res.reset_seconds)

    if not rate_res.allowed:
        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        err_msg = f"Rate limit exceeded. Allowed: {rate_res.limit} requests per window. Please retry after {rate_res.retry_after} seconds."
        if getattr(settings, "metrics_enabled", True):
            try:
                from app.metrics import get_metrics
                get_metrics().record_rate_limit_exceeded(policy="fixed_window")
            except Exception:
                pass
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            provider="gateway",
            http_status=429,
            status="failed",
            duration_ms=duration_ms,
            error_code="rate_limit_exceeded",
            error_message=err_msg,
            cache_status="not_applicable",
        )
        raise RateLimitExceededError(
            message=err_msg,
            retry_after=rate_res.retry_after,
            limit=rate_res.limit,
            remaining=rate_res.remaining,
            reset=rate_res.reset_seconds,
        )

    # Structured access log (safe from prompt content)
    logger.info(
        "Processing chat completion request",
        extra={
            "extra_data": {
                "client_id": client_id,
                "model": request.model,
                "message_count": len(request.messages),
                "temperature": request.temperature,
                "max_tokens": request.max_completion_tokens,
            }
        },
    )

    # 4. Input Guardrails Inspection
    input_res = guardrails.inspect_input(request.messages)
    if not input_res.passed:
        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
        err_msg = "Request content was blocked by input safety guardrails."
        if getattr(settings, "metrics_enabled", True):
            try:
                from app.metrics import get_metrics
                get_metrics().record_guardrail_block(stage="input", detector="rule")
            except Exception:
                pass
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            provider="gateway",
            http_status=400,
            status="failed",
            duration_ms=duration_ms,
            error_code="input_guardrail_blocked",
            error_message=err_msg,
            cache_status="not_applicable",
        )
        raise InputGuardrailBlockedError(message=err_msg, rule_id=input_res.matched_rule_id)

    # 4.5 Semantic Safety Classification (Phase 9.5)
    is_safety_flagged = False
    if settings.safety_classifier_enabled:
        safety_res = await safety_classifier.classify_input(request.messages, settings)
        if safety_res.should_block:
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = f"Request was blocked by semantic safety classification policy ({safety_res.primary_category or 'policy'})."
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_guardrail_block(stage="input", detector="classifier")
                except Exception:
                    pass
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="safety_classification_blocked",
                error_message=err_msg,
                cache_status="not_applicable",
            )
            raise SafetyClassificationBlockedError(
                message=err_msg,
                category=safety_res.primary_category,
                score=safety_res.primary_score,
                action=safety_res.primary_action,
                reason=safety_res.reason,
            )
        else:
            if safety_res.is_redacted and safety_res.redacted_messages:
                request.messages = safety_res.redacted_messages
            if safety_res.is_flagged or safety_res.has_flagged_category:
                is_safety_flagged = True
                response.headers["X-Safety-Risk"] = "flagged"
                flagged_cats = [
                    cat for cat, ev in safety_res.category_evaluations.items()
                    if ev.action == "flag_and_forward"
                ]
                if flagged_cats:
                    response.headers["X-Safety-Category"] = ",".join(flagged_cats)
                elif safety_res.primary_category:
                    response.headers["X-Safety-Category"] = str(safety_res.primary_category)
                response.headers["X-Safety-Score"] = str(safety_res.primary_score)

    # 5. Streaming Completion Handling (Phase 9.2)
    if request.stream:
        if not settings.streaming_enabled:
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            err_msg = "Streaming completions are not enabled or supported in this gateway configuration."
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=400,
                status="failed",
                duration_ms=duration_ms,
                error_code="unsupported_parameter",
                error_message=err_msg,
                cache_status="not_applicable",
                stream=True,
                stream_status="failed_pre_stream",
            )
            raise UnsupportedParameterError(err_msg)

        # Resolve primary provider for requested model
        provider = get_provider_for_model(request.model, settings)
        provider_name = provider.name

        # Streaming Cache Eligibility & Lookup (Phase 11C)
        streaming_cache_active = (
            settings.cache_enabled
            and getattr(settings, "streaming_cache_replay_enabled", True)
        )
        cache_key = None
        cached_data = None
        lookup_status = "miss"
        cache_layer = "exact"
        sem_sim: Optional[float] = None

        if streaming_cache_active:
            cache_key = build_cache_key(
                client_id=client_id,
                provider=provider_name,
                request=request,
                namespace=settings.cache_namespace,
            )
            cached_data, lookup_status = await cache.get(cache_key)
            if lookup_status != "hit" and settings.semantic_cache_enabled:
                sem_data, sem_status, sem_sim, _ = await semantic_cache.get(
                    client_id=client_id,
                    request=request,
                    provider=provider_name,
                )
                if sem_status == "hit" and sem_data:
                    cached_data = sem_data.get("response") or sem_data
                    lookup_status = "hit"
                    cache_layer = "semantic"

        # Check for successful cache hit to replay
        if streaming_cache_active and lookup_status == "hit" and cached_data:
            try:
                cached_resp = ChatCompletionResponse(
                    id=f"chatcmpl-{rid}",
                    object=cached_data.get("object", "chat.completion"),
                    created=int(time.time()),
                    model=cached_data["model"],
                    choices=cached_data["choices"],
                    usage=cached_data["usage"],
                )

                # Output guardrail inspection on cached response
                for choice in cached_resp.choices:
                    choice_content = choice.message.content or ""
                    if choice.message.tool_calls:
                        for tc in choice.message.tool_calls:
                            choice_content += f" {tc.function.arguments}"
                    cached_out_res = guardrails.inspect_output(choice_content)
                    if not cached_out_res.passed:
                        if cache_key and cache_layer == "exact":
                            await cache.delete(cache_key)
                        if getattr(settings, "metrics_enabled", True):
                            try:
                                from app.metrics import get_metrics
                                m = get_metrics()
                                m.record_cache_operation(cache_layer, "stale_eviction")
                                m.record_guardrail_block(stage="output", detector="rule")
                            except Exception:
                                pass
                        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                        err_msg = "Provider response was blocked by output safety guardrails."
                        await _safe_record_outcome(
                            settings=settings,
                            request_id=rid,
                            client_id=client_id,
                            model_requested=request.model,
                            model_actual=cached_resp.model,
                            provider=provider_name,
                            http_status=502,
                            status="failed",
                            duration_ms=duration_ms,
                            error_code="output_guardrail_blocked",
                            error_message=err_msg,
                            cache_status="hit",
                            stream=True,
                            stream_status="failed_pre_stream",
                        )
                        raise OutputGuardrailBlockedError(
                            message=err_msg, rule_id=cached_out_res.matched_rule_id
                        )

                    # Output semantic safety classification on cached entry
                    if settings.safety_classifier_enabled and settings.safety_classifier_inspect_output:
                        out_safety = await safety_classifier.classify_output(choice_content, settings)
                        if out_safety.should_block:
                            if cache_key and cache_layer == "exact":
                                await cache.delete(cache_key)
                            if getattr(settings, "metrics_enabled", True):
                                try:
                                    from app.metrics import get_metrics
                                    m = get_metrics()
                                    m.record_cache_operation(cache_layer, "stale_eviction")
                                    m.record_guardrail_block(stage="output", detector="classifier")
                                except Exception:
                                    pass
                            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                            err_msg = f"Cached response blocked by output safety classification ({out_safety.primary_category or 'policy'})."
                            await _safe_record_outcome(
                                settings=settings,
                                request_id=rid,
                                client_id=client_id,
                                model_requested=request.model,
                                model_actual=cached_resp.model,
                                provider=provider_name,
                                http_status=502,
                                status="failed",
                                duration_ms=duration_ms,
                                error_code="output_safety_blocked",
                                error_message=err_msg,
                                cache_status="hit",
                                stream=True,
                                stream_status="failed_pre_stream",
                            )
                            raise SafetyClassificationBlockedError(
                                message=err_msg,
                                category=out_safety.primary_category,
                                score=out_safety.primary_score,
                                action=out_safety.primary_action,
                                reason=out_safety.reason,
                            )

                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        get_metrics().record_cache_operation(cache_layer, "hit")
                    except Exception:
                        pass

                replay_headers = {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Request-ID": rid,
                    "X-Serving-Provider": provider_name,
                    "X-Serving-Model": cached_resp.model,
                    "X-Requested-Model": request.model,
                    "X-Failover-Occurred": "false",
                    "X-Failover-Attempts": "0",
                    "X-Cache": "HIT",
                    "X-Cache-Layer": cache_layer,
                }
                if cache_layer == "semantic" and sem_sim is not None:
                    replay_headers["X-Cache-Similarity"] = str(round(sem_sim, 4))
                if settings.rate_limit_enabled and rate_res.status in ("ok", "exceeded"):
                    replay_headers["X-RateLimit-Limit"] = str(rate_res.limit)
                    replay_headers["X-RateLimit-Remaining"] = str(rate_res.remaining)
                    replay_headers["X-RateLimit-Reset"] = str(rate_res.reset_seconds)

                return StreamingResponse(
                    _sse_replay_generator(
                        cached_resp=cached_resp,
                        request_id=rid,
                        client_id=client_id,
                        request=request,
                        provider_name=provider_name,
                        route_start=route_start,
                        settings=settings,
                        cache_layer=cache_layer,
                    ),
                    media_type="text/event-stream",
                    headers=replay_headers,
                )

            except AppException:
                raise
            except Exception as parse_exc:
                logger.warning(f"Corrupted cache entry parsing failed, treating as miss: {parse_exc}")
                if cache_key and cache_layer == "exact":
                    await cache.delete(cache_key)
                lookup_status = "miss"

        # Determine cache status metadata for streaming request
        if streaming_cache_active:
            if lookup_status == "error":
                stream_cache_status = "error"
                stream_cache_hdr = "ERROR"
                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        get_metrics().record_cache_operation("exact", "error")
                    except Exception:
                        pass
            else:
                stream_cache_status = "miss"
                stream_cache_hdr = "MISS"
                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        get_metrics().record_cache_operation("exact", "miss")
                    except Exception:
                        pass
        else:
            stream_cache_status = "disabled" if not settings.cache_enabled else "bypass"
            stream_cache_hdr = "BYPASS"
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("exact", "bypass")
                except Exception:
                    pass

        # Pre-stream multi-provider failover initialization
        # Primary provider and candidate fallbacks are tried before returning headers or emitting chunks
        try:
            init_res = await init_stream_with_failover(
                request=request,
                settings=settings,
                allow_failover=effective_allow_failover,
                provider_resolver=get_provider_for_model,
                overall_start_time=route_start,
            )
        except Exception as pre_stream_exc:
            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
            http_status = getattr(pre_stream_exc, "status_code", 500)
            err_code = getattr(pre_stream_exc, "error_code", "provider_error")
            err_msg = getattr(pre_stream_exc, "message", str(pre_stream_exc))
            failover_hdrs = getattr(pre_stream_exc, "headers", {})
            for hk, hv in failover_hdrs.items():
                response.headers[hk] = hv
            response.headers["X-Cache"] = stream_cache_hdr
            await _safe_record_outcome(
                settings=settings,
                request_id=rid,
                client_id=client_id,
                model_requested=request.model,
                provider="gateway",
                http_status=http_status,
                status="failed",
                duration_ms=duration_ms,
                error_code=err_code,
                error_message=err_msg,
                cache_status=stream_cache_status,
                stream=True,
                stream_status="failed_pre_stream",
            )
            raise pre_stream_exc

        # At this point, the primary or fallback provider successfully connected and yielded chunk #0.
        # Commit to this provider and model; no further cross-provider failover can occur.
        serving_provider = init_res.serving_provider
        serving_model = init_res.serving_model
        first_chunk = init_res.first_chunk
        remaining_stream = init_res.stream_generator
        failover_occurred = init_res.failover_occurred
        attempts_count = len(init_res.attempts)
        attempt_seq_json = json.dumps([a.to_dict() for a in init_res.attempts])
        initial_latency_ms = (
            init_res.attempts[-1].latency_ms if init_res.attempts else None
        )

        async def sse_event_generator():
            stream_outcome = "completed"
            accumulated_text = ""
            accumulated_tool_calls_dict: Dict[int, Dict[str, Any]] = {}
            final_finish_reason: Optional[str] = None
            final_input_tokens: Optional[int] = None
            final_output_tokens: Optional[int] = None
            final_total_tokens: Optional[int] = None
            final_usage_source = "unavailable"
            final_is_estimate = False
            last_stream_err_code: Optional[str] = None
            last_stream_err_msg: Optional[str] = None

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().increment_active_streams()
                except Exception:
                    pass

            def extract_usage(chunk: ChatCompletionChunk) -> None:
                nonlocal final_input_tokens, final_output_tokens, final_total_tokens, final_usage_source, final_is_estimate
                if chunk.usage:
                    if chunk.usage.prompt_tokens is not None:
                        final_input_tokens = chunk.usage.prompt_tokens
                    if chunk.usage.completion_tokens is not None:
                        final_output_tokens = chunk.usage.completion_tokens
                    if chunk.usage.total_tokens is not None:
                        final_total_tokens = chunk.usage.total_tokens
                    final_usage_source = chunk.usage.usage_source
                    final_is_estimate = chunk.usage.is_mock_estimate

            def process_chunk_for_cache(c: ChatCompletionChunk) -> None:
                nonlocal final_finish_reason
                if c.choices:
                    ch = c.choices[0]
                    if ch.finish_reason:
                        final_finish_reason = ch.finish_reason
                    if ch.delta:
                        if ch.delta.tool_calls:
                            for tc in ch.delta.tool_calls:
                                idx = tc.index
                                if idx not in accumulated_tool_calls_dict:
                                    accumulated_tool_calls_dict[idx] = {
                                        "id": tc.id or f"call_{idx}",
                                        "name": (tc.function.name if tc.function and tc.function.name else ""),
                                        "arguments": (tc.function.arguments if tc.function and tc.function.arguments else ""),
                                    }
                                else:
                                    if tc.id:
                                        accumulated_tool_calls_dict[idx]["id"] = tc.id
                                    if tc.function and tc.function.name:
                                        accumulated_tool_calls_dict[idx]["name"] = tc.function.name
                                    if tc.function and tc.function.arguments:
                                        accumulated_tool_calls_dict[idx]["arguments"] += tc.function.arguments

            try:
                # 1. Process and yield first chunk
                if first_chunk:
                    extract_usage(first_chunk)
                    process_chunk_for_cache(first_chunk)
                    delta_text = ""
                    if first_chunk.choices:
                        choice_delta = first_chunk.choices[0].delta
                        if choice_delta.content:
                            delta_text += choice_delta.content
                        if choice_delta.tool_calls:
                            for tc in choice_delta.tool_calls:
                                if tc.function and tc.function.arguments:
                                    delta_text += tc.function.arguments

                    if delta_text:
                        accumulated_text += delta_text
                        guard_res = guardrails.inspect_output(accumulated_text)
                        if not guard_res.passed:
                            stream_outcome = "failed_post_stream"
                            last_stream_err_code = "output_guardrail_blocked"
                            last_stream_err_msg = "Content was blocked by output safety guardrails."
                            if getattr(settings, "metrics_enabled", True):
                                try:
                                    from app.metrics import get_metrics
                                    get_metrics().record_guardrail_block(stage="output", detector="rule")
                                except Exception:
                                    pass
                            err_payload = json.dumps({
                                "error": {
                                    "message": last_stream_err_msg,
                                    "type": "guardrail_error",
                                    "code": "output_guardrail_blocked",
                                    "rule_id": guard_res.matched_rule_id,
                                    "request_id": rid,
                                }
                            })
                            yield f"data: {err_payload}\n\n"
                            yield "data: [DONE]\n\n"
                            return

                    yield first_chunk.to_sse_event()

                # 2. Iterate remaining stream
                async for chunk in remaining_stream:
                    extract_usage(chunk)
                    process_chunk_for_cache(chunk)
                    delta_text = ""
                    if chunk.choices:
                        choice_delta = chunk.choices[0].delta
                        if choice_delta.content:
                            delta_text += choice_delta.content
                        if choice_delta.tool_calls:
                            for tc in choice_delta.tool_calls:
                                if tc.function and tc.function.arguments:
                                    delta_text += tc.function.arguments

                    if delta_text:
                        accumulated_text += delta_text
                        guard_res = guardrails.inspect_output(accumulated_text)
                        if not guard_res.passed:
                            stream_outcome = "failed_post_stream"
                            last_stream_err_code = "output_guardrail_blocked"
                            last_stream_err_msg = "Content was blocked by output safety guardrails."
                            if getattr(settings, "metrics_enabled", True):
                                try:
                                    from app.metrics import get_metrics
                                    get_metrics().record_guardrail_block(stage="output", detector="rule")
                                except Exception:
                                    pass
                            err_payload = json.dumps({
                                "error": {
                                    "message": last_stream_err_msg,
                                    "type": "guardrail_error",
                                    "code": "output_guardrail_blocked",
                                    "rule_id": guard_res.matched_rule_id,
                                    "request_id": rid,
                                }
                            })
                            yield f"data: {err_payload}\n\n"
                            yield "data: [DONE]\n\n"
                            return

                    yield chunk.to_sse_event()

                # 3. Stream completed normally
                yield "data: [DONE]\n\n"

                # Populate streaming cache on clean completion
                if (
                    streaming_cache_active
                    and cache_key
                    and stream_outcome == "completed"
                    and not failover_occurred
                    and not is_safety_flagged
                ):
                    try:
                        acc_tool_calls = None
                        if accumulated_tool_calls_dict:
                            acc_tool_calls = [
                                ChatCompletionMessageToolCall(
                                    id=tc_d["id"],
                                    type="function",
                                    function=FunctionCall(
                                        name=tc_d["name"],
                                        arguments=tc_d["arguments"],
                                    ),
                                )
                                for _, tc_d in sorted(accumulated_tool_calls_dict.items())
                            ]
                        full_response = ChatCompletionResponse(
                            id=f"chatcmpl-{rid}",
                            object="chat.completion",
                            created=int(time.time()),
                            model=serving_model,
                            choices=[
                                ChatChoice(
                                    index=0,
                                    message=ChatChoiceMessage(
                                        role="assistant",
                                        content=accumulated_text if accumulated_text else None,
                                        tool_calls=acc_tool_calls,
                                    ),
                                    finish_reason=final_finish_reason or ("tool_calls" if acc_tool_calls else "stop"),
                                )
                            ],
                            usage=UsageInfo(
                                prompt_tokens=final_input_tokens,
                                completion_tokens=final_output_tokens,
                                total_tokens=final_total_tokens,
                                usage_source=final_usage_source,
                                is_mock_estimate=final_is_estimate,
                            ),
                        )
                        await cache.set(cache_key, full_response, settings.cache_ttl_seconds)
                        if settings.semantic_cache_enabled:
                            await semantic_cache.set(
                                client_id=client_id,
                                request=request,
                                response=full_response,
                                provider=serving_provider,
                                ttl_seconds=settings.semantic_cache_ttl_seconds,
                            )
                    except Exception as cache_pop_exc:
                        logger.warning(f"Failed to populate streaming cache for {rid}: {cache_pop_exc}")

            except asyncio.CancelledError:
                stream_outcome = "cancelled"
                last_stream_err_code = "client_cancelled"
                last_stream_err_msg = "Client disconnected during streaming response."
                logger.info(f"Streaming request {rid} was cancelled by client.")
                raise

            except Exception as stream_exc:
                stream_outcome = "failed_post_stream"
                last_stream_err_code = getattr(stream_exc, "error_code", "stream_error")
                last_stream_err_msg = "Upstream provider error during streaming response."
                if isinstance(stream_exc, AppException):
                    last_stream_err_msg = stream_exc.message

                logger.error(f"Streaming failure after content emitted for request {rid}: {stream_exc}")
                err_payload = json.dumps({
                    "error": {
                        "message": last_stream_err_msg,
                        "type": "stream_error",
                        "code": last_stream_err_code,
                        "request_id": rid,
                    }
                })
                yield f"data: {err_payload}\n\n"
                yield "data: [DONE]\n\n"

            finally:
                if hasattr(remaining_stream, "aclose"):
                    try:
                        await remaining_stream.aclose()
                    except Exception:
                        pass

                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        m = get_metrics()
                        m.decrement_active_streams()
                        m.record_tokens(
                            input_tokens=final_input_tokens,
                            output_tokens=final_output_tokens,
                            provider=serving_provider,
                            model=serving_model,
                            source=final_usage_source,
                        )
                    except Exception:
                        pass

                total_duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                record_status = "success" if stream_outcome == "completed" else "failed"
                if stream_outcome == "completed":
                    record_http_status = 200
                elif stream_outcome == "cancelled":
                    record_http_status = 499
                else:
                    record_http_status = 502

                await _safe_record_outcome(
                    settings=settings,
                    request_id=rid,
                    client_id=client_id,
                    model_requested=request.model,
                    model_actual=serving_model,
                    provider=serving_provider,
                    http_status=record_http_status,
                    status=record_status,
                    duration_ms=total_duration_ms,
                    provider_latency_ms=initial_latency_ms,
                    input_tokens=final_input_tokens,
                    output_tokens=final_output_tokens,
                    total_tokens=final_total_tokens,
                    usage_source=final_usage_source,
                    is_estimate=final_is_estimate,
                    cache_status=stream_cache_status,
                    error_code=last_stream_err_code,
                    error_message=last_stream_err_msg,
                    attempts_count=attempts_count,
                    failover_occurred=failover_occurred,
                    attempt_sequence=attempt_seq_json,
                    stream=True,
                    stream_status=stream_outcome,
                )

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": rid,
            "X-Serving-Provider": serving_provider,
            "X-Serving-Model": serving_model,
            "X-Requested-Model": request.model,
            "X-Failover-Occurred": "true" if failover_occurred else "false",
            "X-Failover-Attempts": str(attempts_count),
            "X-Cache": stream_cache_hdr,
        }
        if settings.rate_limit_enabled and rate_res.status in ("ok", "exceeded"):
            headers["X-RateLimit-Limit"] = str(rate_res.limit)
            headers["X-RateLimit-Remaining"] = str(rate_res.remaining)
            headers["X-RateLimit-Reset"] = str(rate_res.reset_seconds)

        return StreamingResponse(
            sse_event_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    # 6. Non-Streaming: Resolve provider
    provider = get_provider_for_model(request.model, settings)
    provider_name = provider.name

    # 7. Non-Streaming: Cache eligibility and lookup
    cache_status = "disabled"
    cache_key: Optional[str] = None

    if not settings.cache_enabled:
        response.headers["X-Cache"] = "DISABLED"
        cache_status = "disabled"
        if getattr(settings, "metrics_enabled", True):
            try:
                from app.metrics import get_metrics
                get_metrics().record_cache_operation("exact", "bypass")
            except Exception:
                pass
    else:
        cache_key = build_cache_key(
            client_id=client_id,
            provider=provider_name,
            request=request,
            namespace=settings.cache_namespace,
        )
        cached_data, lookup_status = await cache.get(cache_key)

        if lookup_status == "hit" and cached_data:
            try:
                # Reconstruct stored response ensuring current request receives fresh ID and timestamp
                cached_resp = ChatCompletionResponse(
                    id=f"chatcmpl-{rid}",
                    object=cached_data.get("object", "chat.completion"),
                    created=int(time.time()),
                    model=cached_data["model"],
                    choices=cached_data["choices"],
                    usage=cached_data["usage"],
                )

                # Output guardrail inspection and semantic safety check on cached response
                for choice in cached_resp.choices:
                    choice_content = choice.message.content or ""
                    if choice.message.tool_calls:
                        for tc in choice.message.tool_calls:
                            choice_content += f" {tc.function.arguments}"
                    cached_out_res = guardrails.inspect_output(choice_content)
                    if not cached_out_res.passed:
                        # Invalidate stale cache entry immediately
                        if cache_key:
                            await cache.delete(cache_key)
                        if getattr(settings, "metrics_enabled", True):
                            try:
                                from app.metrics import get_metrics
                                m = get_metrics()
                                m.record_cache_operation("exact", "stale_eviction")
                                m.record_guardrail_block(stage="output", detector="rule")
                            except Exception:
                                pass
                        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                        err_msg = "Provider response was blocked by output safety guardrails."
                        await _safe_record_outcome(
                            settings=settings,
                            request_id=rid,
                            client_id=client_id,
                            model_requested=request.model,
                            model_actual=cached_resp.model,
                            provider=provider_name,
                            http_status=502,
                            status="failed",
                            duration_ms=duration_ms,
                            error_code="output_guardrail_blocked",
                            error_message=err_msg,
                            cache_status="hit",
                        )
                        raise OutputGuardrailBlockedError(
                            message=err_msg, rule_id=cached_out_res.matched_rule_id
                        )

                    # Output semantic safety classification on cached entry
                    if settings.safety_classifier_enabled and settings.safety_classifier_inspect_output:
                        out_safety = await safety_classifier.classify_output(choice_content, settings)
                        if out_safety.should_block:
                            if cache_key:
                                await cache.delete(cache_key)
                            if getattr(settings, "metrics_enabled", True):
                                try:
                                    from app.metrics import get_metrics
                                    m = get_metrics()
                                    m.record_cache_operation("exact", "stale_eviction")
                                    m.record_guardrail_block(stage="output", detector="classifier")
                                except Exception:
                                    pass
                            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                            err_msg = f"Cached response blocked by output safety classification ({out_safety.primary_category or 'policy'})."
                            await _safe_record_outcome(
                                settings=settings,
                                request_id=rid,
                                client_id=client_id,
                                model_requested=request.model,
                                model_actual=cached_resp.model,
                                provider=provider_name,
                                http_status=502,
                                status="failed",
                                duration_ms=duration_ms,
                                error_code="output_safety_blocked",
                                error_message=err_msg,
                                cache_status="hit",
                            )
                            raise SafetyClassificationBlockedError(
                                message=err_msg,
                                category=out_safety.primary_category,
                                score=out_safety.primary_score,
                                action=out_safety.primary_action,
                                reason=out_safety.reason,
                            )

                duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Cache-Layer"] = "exact"
                response.headers["X-Serving-Provider"] = provider_name
                response.headers["X-Serving-Model"] = cached_resp.model
                response.headers["X-Requested-Model"] = request.model
                response.headers["X-Failover-Occurred"] = "false"
                response.headers["X-Failover-Attempts"] = "0"
                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        get_metrics().record_cache_operation("exact", "hit")
                    except Exception:
                        pass

                # Persist cache hit: no upstream provider call, zero incremental cost
                await _safe_record_outcome(
                    settings=settings,
                    request_id=rid,
                    client_id=client_id,
                    model_requested=request.model,
                    model_actual=cached_resp.model,
                    provider=provider_name,
                    http_status=200,
                    status="success",
                    duration_ms=duration_ms,
                    provider_latency_ms=None,
                    input_tokens=cached_resp.usage.prompt_tokens,
                    output_tokens=cached_resp.usage.completion_tokens,
                    total_tokens=cached_resp.usage.total_tokens,
                    usage_source="cache_hit",
                    is_estimate=cached_resp.usage.is_mock_estimate,
                    cache_status="hit",
                )
                return cached_resp
            except AppException:
                raise
            except Exception as parse_exc:
                logger.warning(f"Corrupted cache entry parsing failed, treating as miss: {parse_exc}")
                cache_status = "miss"
        elif lookup_status == "error":
            cache_status = "error"
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("exact", "error")
                except Exception:
                    pass
        else:
            cache_status = "miss"
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("exact", "miss")
                except Exception:
                    pass

    # Level 2: Optional Semantic Cache Lookup (Phase 9.4)
    if settings.semantic_cache_enabled:
        sem_data, sem_status, sem_sim, sem_reason = await semantic_cache.get(
            client_id=client_id,
            request=request,
            provider=provider_name,
        )
        if sem_status == "hit" and sem_data:
            sem_entry_id = sem_data.get("_entry_id")
            try:
                sem_resp = ChatCompletionResponse(
                    id=f"chatcmpl-{rid}",
                    object=sem_data.get("object", "chat.completion"),
                    created=int(time.time()),
                    model=sem_data["model"],
                    choices=sem_data["choices"],
                    usage=sem_data["usage"],
                )

                # Output guardrail inspection and semantic safety check on cached response
                for choice in sem_resp.choices:
                    choice_content = choice.message.content or ""
                    if choice.message.tool_calls:
                        for tc in choice.message.tool_calls:
                            choice_content += f" {tc.function.arguments}"
                    cached_out_res = guardrails.inspect_output(choice_content)
                    if not cached_out_res.passed:
                        # Invalidate stale semantic entry immediately from Redis
                        if sem_entry_id:
                            await semantic_cache.delete_entry(
                                client_id=client_id,
                                entry_id=sem_entry_id,
                                model=request.model,
                            )
                        if getattr(settings, "metrics_enabled", True):
                            try:
                                from app.metrics import get_metrics
                                m = get_metrics()
                                m.record_cache_operation("semantic", "stale_eviction")
                                m.record_guardrail_block(stage="output", detector="rule")
                            except Exception:
                                pass
                        duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                        err_msg = "Provider response was blocked by output safety guardrails."
                        await _safe_record_outcome(
                            settings=settings,
                            request_id=rid,
                            client_id=client_id,
                            model_requested=request.model,
                            model_actual=sem_resp.model,
                            provider=provider_name,
                            http_status=502,
                            status="failed",
                            duration_ms=duration_ms,
                            error_code="output_guardrail_blocked",
                            error_message=err_msg,
                            cache_status="semantic_hit",
                        )
                        raise OutputGuardrailBlockedError(
                            message=err_msg, rule_id=cached_out_res.matched_rule_id
                        )

                    # Output semantic safety classification on semantic cached entry
                    if settings.safety_classifier_enabled and settings.safety_classifier_inspect_output:
                        out_safety = await safety_classifier.classify_output(choice_content, settings)
                        if out_safety.should_block:
                            if sem_entry_id:
                                await semantic_cache.delete_entry(
                                    client_id=client_id,
                                    entry_id=sem_entry_id,
                                    model=request.model,
                                    )
                            if getattr(settings, "metrics_enabled", True):
                                try:
                                    from app.metrics import get_metrics
                                    m = get_metrics()
                                    m.record_cache_operation("semantic", "stale_eviction")
                                    m.record_guardrail_block(stage="output", detector="classifier")
                                except Exception:
                                    pass
                            duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                            err_msg = f"Semantic cached response blocked by output safety classification ({out_safety.primary_category or 'policy'})."
                            await _safe_record_outcome(
                                settings=settings,
                                request_id=rid,
                                client_id=client_id,
                                model_requested=request.model,
                                model_actual=sem_resp.model,
                                provider=provider_name,
                                http_status=502,
                                status="failed",
                                duration_ms=duration_ms,
                                error_code="output_safety_blocked",
                                error_message=err_msg,
                                cache_status="semantic_hit",
                            )
                            raise SafetyClassificationBlockedError(
                                message=err_msg,
                                category=out_safety.primary_category,
                                score=out_safety.primary_score,
                                action=out_safety.primary_action,
                                reason=out_safety.reason,
                            )

                duration_ms = round((time.perf_counter() - route_start) * 1000, 2)
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Cache-Layer"] = "semantic"
                response.headers["X-Cache-Similarity"] = f"{sem_sim:.4f}"
                response.headers["X-Serving-Provider"] = provider_name
                response.headers["X-Serving-Model"] = sem_resp.model
                response.headers["X-Requested-Model"] = request.model
                response.headers["X-Failover-Occurred"] = "false"
                response.headers["X-Failover-Attempts"] = "0"
                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        get_metrics().record_cache_operation("semantic", "hit")
                    except Exception:
                        pass

                # Persist semantic cache hit: zero incremental cloud cost, distinct provenance
                await _safe_record_outcome(
                    settings=settings,
                    request_id=rid,
                    client_id=client_id,
                    model_requested=request.model,
                    model_actual=sem_resp.model,
                    provider=provider_name,
                    http_status=200,
                    status="success",
                    duration_ms=duration_ms,
                    provider_latency_ms=None,
                    input_tokens=sem_resp.usage.prompt_tokens,
                    output_tokens=sem_resp.usage.completion_tokens,
                    total_tokens=sem_resp.usage.total_tokens,
                    usage_source="semantic_cache_hit",
                    is_estimate=sem_resp.usage.is_mock_estimate,
                    cache_status="semantic_hit",
                )
                return sem_resp
            except AppException:
                raise
            except Exception as parse_exc:
                logger.warning(f"Corrupted semantic cache entry parsing failed, treating as miss: {parse_exc}")
        elif sem_status == "error":
            logger.warning(f"Semantic cache error on lookup: {sem_reason}")
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("semantic", "error")
                except Exception:
                    pass
        elif sem_status == "bypass":
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("semantic", "bypass")
                except Exception:
                    pass
        else:
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("semantic", "miss")
                except Exception:
                    pass

    # 7. Execute completion with multi-provider failover
    failover_res = await execute_with_failover(
        request=request,
        settings=settings,
        allow_failover=effective_allow_failover,
        provider_resolver=get_provider_for_model,
        overall_start_time=route_start,
    )

    attempts_count = len(failover_res.attempts)
    failover_occurred = failover_res.failover_occurred
    attempt_seq_json = json.dumps([a.to_dict() for a in failover_res.attempts])
    serving_provider = failover_res.serving_provider or provider_name
    serving_model = failover_res.serving_model or request.model
    provider_latency_ms = (
        failover_res.attempts[-1].latency_ms if failover_res.attempts else None
    )
    duration_ms = round((time.perf_counter() - route_start) * 1000, 2)

    # 8. Handle successful completion
    if failover_res.response is not None:
        prov_response = failover_res.response

        # Output guardrail inspection on provider response
        for choice in prov_response.choices:
            choice_content = choice.message.content or ""
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    choice_content += f" {tc.function.arguments}"
            out_res = guardrails.inspect_output(choice_content)
            if not out_res.passed:
                err_msg = "Provider response was blocked by output safety guardrails."
                if getattr(settings, "metrics_enabled", True):
                    try:
                        from app.metrics import get_metrics
                        get_metrics().record_guardrail_block(stage="output", detector="rule")
                    except Exception:
                        pass
                # Do NOT cache blocked responses!
                await _safe_record_outcome(
                    settings=settings,
                    request_id=rid,
                    client_id=client_id,
                    model_requested=request.model,
                    model_actual=serving_model,
                    provider=serving_provider,
                    http_status=502,
                    status="failed",
                    duration_ms=duration_ms,
                    provider_latency_ms=provider_latency_ms,
                    input_tokens=prov_response.usage.prompt_tokens,
                    output_tokens=prov_response.usage.completion_tokens,
                    total_tokens=prov_response.usage.total_tokens,
                    usage_source=prov_response.usage.usage_source,
                    is_estimate=prov_response.usage.is_mock_estimate,
                    error_code="output_guardrail_blocked",
                    error_message=err_msg,
                    cache_status="not_applicable",
                    attempts_count=attempts_count,
                    failover_occurred=failover_occurred,
                    attempt_sequence=attempt_seq_json,
                )
                raise OutputGuardrailBlockedError(
                    message=err_msg, rule_id=out_res.matched_rule_id
                )

            # Output semantic safety classification on provider response
            if settings.safety_classifier_enabled and settings.safety_classifier_inspect_output:
                out_safety = await safety_classifier.classify_output(choice_content, settings)
                if out_safety.should_block:
                    err_msg = f"Provider response was blocked by output safety classification ({out_safety.primary_category or 'policy'})."
                    if getattr(settings, "metrics_enabled", True):
                        try:
                            from app.metrics import get_metrics
                            get_metrics().record_guardrail_block(stage="output", detector="classifier")
                        except Exception:
                            pass
                    await _safe_record_outcome(
                        settings=settings,
                        request_id=rid,
                        client_id=client_id,
                        model_requested=request.model,
                        model_actual=serving_model,
                        provider=serving_provider,
                        http_status=502,
                        status="failed",
                        duration_ms=duration_ms,
                        provider_latency_ms=provider_latency_ms,
                        input_tokens=prov_response.usage.prompt_tokens,
                        output_tokens=prov_response.usage.completion_tokens,
                        total_tokens=prov_response.usage.total_tokens,
                        usage_source=prov_response.usage.usage_source,
                        is_estimate=prov_response.usage.is_mock_estimate,
                        error_code="output_safety_blocked",
                        error_message=err_msg,
                        cache_status="not_applicable",
                        attempts_count=attempts_count,
                        failover_occurred=failover_occurred,
                        attempt_sequence=attempt_seq_json,
                    )
                    raise SafetyClassificationBlockedError(
                        message=err_msg,
                        category=out_safety.primary_category,
                        score=out_safety.primary_score,
                        action=out_safety.primary_action,
                        reason=out_safety.reason,
                    )
                elif out_safety.is_flagged or out_safety.has_flagged_category:
                    is_safety_flagged = True
                    response.headers["X-Safety-Risk"] = "flagged"

        # Apply failover observability headers
        response.headers["X-Serving-Provider"] = serving_provider
        response.headers["X-Serving-Model"] = serving_model
        response.headers["X-Requested-Model"] = request.model
        response.headers["X-Failover-Occurred"] = "true" if failover_occurred else "false"
        response.headers["X-Failover-Attempts"] = str(attempts_count)

        # Caching logic: prevent cross-model cache pollution on failover or safety flags
        if failover_occurred or is_safety_flagged:
            response.headers["X-Cache"] = "BYPASS"
            cache_status = "bypass"
            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_cache_operation("exact", "bypass")
                except Exception:
                    pass
        else:
            if cache_status == "error":
                response.headers["X-Cache"] = "ERROR"
            elif cache_status == "disabled":
                response.headers["X-Cache"] = "DISABLED"
            elif cache_status == "not_applicable":
                response.headers["X-Cache"] = "BYPASS"
            else:
                response.headers["X-Cache"] = "MISS"

            # Cache eligible responses only when no failover occurred
            if cache_key and cache_status == "miss":
                await cache.set(cache_key, prov_response, settings.cache_ttl_seconds)

            # Level 2 Semantic Cache insertion (if enabled and eligible)
            if settings.semantic_cache_enabled:
                await semantic_cache.set(
                    client_id=client_id,
                    request=request,
                    response=prov_response,
                    provider=serving_provider,
                    ttl_seconds=settings.semantic_cache_ttl_seconds,
                )

        if getattr(settings, "metrics_enabled", True):
            try:
                from app.metrics import get_metrics
                get_metrics().record_tokens(
                    input_tokens=prov_response.usage.prompt_tokens,
                    output_tokens=prov_response.usage.completion_tokens,
                    provider=serving_provider,
                    model=serving_model,
                    source=prov_response.usage.usage_source,
                )
            except Exception:
                pass

        # Record successful completion and usage
        await _safe_record_outcome(
            settings=settings,
            request_id=rid,
            client_id=client_id,
            model_requested=request.model,
            model_actual=serving_model,
            provider=serving_provider,
            http_status=200,
            status="success",
            duration_ms=duration_ms,
            provider_latency_ms=provider_latency_ms,
            input_tokens=prov_response.usage.prompt_tokens,
            output_tokens=prov_response.usage.completion_tokens,
            total_tokens=prov_response.usage.total_tokens,
            usage_source=prov_response.usage.usage_source,
            is_estimate=prov_response.usage.is_mock_estimate,
            cache_status=cache_status,
            attempts_count=attempts_count,
            failover_occurred=failover_occurred,
            attempt_sequence=attempt_seq_json,
        )
        return prov_response

    # 9. Handle failure when all candidate attempts failed or stopped
    last_exc = failover_res.last_error or ProviderError("Upstream provider failure.")
    failover_hdrs = {
        "X-Serving-Provider": serving_provider,
        "X-Serving-Model": serving_model,
        "X-Requested-Model": request.model,
        "X-Failover-Occurred": "true" if failover_occurred else "false",
        "X-Failover-Attempts": str(attempts_count),
    }
    for hk, hv in failover_hdrs.items():
        response.headers[hk] = hv

    if isinstance(last_exc, AppException):
        if getattr(last_exc, "headers", None) is None:
            last_exc.headers = {}
        last_exc.headers.update(failover_hdrs)
    elif isinstance(last_exc, (asyncio.TimeoutError, TimeoutError)):
        err_msg = f"Upstream provider timed out after {settings.provider_timeout_seconds} seconds."
        last_exc = ProviderTimeoutError(err_msg)
        last_exc.headers = failover_hdrs
    else:
        try:
            last_exc.headers = failover_hdrs
        except Exception:
            pass

    if cache_status == "error":
        response.headers["X-Cache"] = "ERROR"
    elif cache_status == "disabled":
        response.headers["X-Cache"] = "DISABLED"
    elif cache_status == "not_applicable":
        response.headers["X-Cache"] = "BYPASS"
    else:
        response.headers["X-Cache"] = "MISS"

    if isinstance(last_exc, AppException):
        http_status = last_exc.status_code
        err_code = last_exc.error_code
        err_msg = last_exc.message
    else:
        http_status = 500
        err_code = "internal_error"
        err_msg = str(last_exc)

    await _safe_record_outcome(
        settings=settings,
        request_id=rid,
        client_id=client_id,
        model_requested=request.model,
        model_actual=serving_model,
        provider=serving_provider,
        http_status=http_status,
        status="failed",
        duration_ms=duration_ms,
        provider_latency_ms=provider_latency_ms,
        error_code=err_code,
        error_message=err_msg,
        cache_status=cache_status,
        attempts_count=attempts_count,
        failover_occurred=failover_occurred,
        attempt_sequence=attempt_seq_json,
    )
    raise last_exc


@router.get(
    "/v1/usage/summary",
    response_model=UsageSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_usage_summary(
    client_id: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
) -> UsageSummaryResponse:
    """Return aggregated token metrics and estimated cloud costs strictly scoped to the authenticated client."""
    db_svc = DatabaseService(engine=get_engine(settings.database_url))
    summary_data = await asyncio.to_thread(db_svc.get_usage_summary, client_id=client_id)
    return UsageSummaryResponse(**summary_data)


@router.get(
    "/v1/usage/export",
    status_code=status.HTTP_200_OK,
)
async def export_usage_csv(
    client_id: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Export request and usage records for the authenticated client as a CSV download."""
    db_svc = DatabaseService(engine=get_engine(settings.database_url))
    csv_content = await asyncio.to_thread(db_svc.export_records_csv, client_id=client_id)
    filename = f"usage_{client_id}_{int(time.time())}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
