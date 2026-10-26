"""Multi-provider failover classification, model validation, and execution orchestration."""

import asyncio
from dataclasses import asdict, dataclass
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
import uuid
import httpx

from app.api.schemas import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.config import Settings
from app.core.errors import (
    AppException,
    AuthenticationError,
    InputGuardrailBlockedError,
    InvalidModelError,
    OutputGuardrailBlockedError,
    PayloadTooLargeError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitExceededError,
    RateLimiterUnavailableError,
    UnsupportedParameterError,
)
from app.core.logging import logger
from app.pricing.calculator import pricing_engine
from app.providers.base import (
    BaseLLMProvider,
    model_supports_streaming,
    model_supports_streaming_tools,
    model_supports_tools,
)


@dataclass
class FailoverAttempt:
    """Record of an individual provider/model invocation attempt."""

    attempt_number: int
    provider: str
    model: str
    success: bool
    latency_ms: float
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    failure_category: Optional[str] = None
    retry_after: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return sanitized dictionary representation for persistence and logging."""
        return {
            "attempt": self.attempt_number,
            "provider": self.provider,
            "model": self.model,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "failure_category": self.failure_category,
            "retry_after": self.retry_after,
        }


@dataclass
class FailoverExecutionResult:
    """Aggregate result from failover orchestrator execution."""

    response: Optional[ChatCompletionResponse]
    serving_provider: Optional[str]
    serving_model: Optional[str]
    attempts: List[FailoverAttempt]
    failover_occurred: bool
    last_error: Optional[Exception]


@dataclass
class StreamingFailoverInitResult:
    """Result of pre-stream failover resolution before first chunk emission."""

    first_chunk: ChatCompletionChunk
    stream_generator: AsyncIterator[ChatCompletionChunk]
    serving_provider: str
    serving_model: str
    attempts: List[FailoverAttempt]
    failover_occurred: bool


def classify_failure(
    exc: Exception, settings: Settings
) -> Tuple[bool, str, Optional[float]]:
    """Classify an exception as eligible or ineligible for automatic failover.

    Returns:
        (is_eligible, failure_category, retry_after)
    """
    # 1. Strictly Ineligible Categories (do not failover)
    if isinstance(exc, (ProviderAuthenticationError, AuthenticationError)):
        return False, "ineligible_authentication", None

    # SafeRoute's client rate limit or rate limiter unavailable MUST NEVER trigger provider failover
    if isinstance(exc, (RateLimitExceededError, RateLimiterUnavailableError)) or getattr(exc, "error_code", None) in (
        "rate_limit_exceeded",
        "rate_limiter_unavailable",
    ):
        return False, "ineligible_gateway_rate_limit", None

    if isinstance(
        exc,
        (
            InvalidModelError,
            UnsupportedParameterError,
            PayloadTooLargeError,
        ),
    ):
        return False, "ineligible_client_error", None

    if isinstance(exc, (InputGuardrailBlockedError, OutputGuardrailBlockedError)):
        return False, "ineligible_guardrail", None

    # 2. Timeout Failures (Eligible)
    if isinstance(exc, (ProviderTimeoutError, asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return True, "timeout", None

    # 3. Rate Limit Failures (Upstream Provider HTTP 429 - Eligible, subject to bounded retry hints)
    if isinstance(exc, ProviderRateLimitError):
        retry_after = getattr(exc, "retry_after", None)
        return True, "rate_limit", retry_after

    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code if exc.response is not None else 500
        if status_code == 429:
            retry_after = None
            if exc.response is not None and "retry-after" in exc.response.headers:
                try:
                    retry_after = float(exc.response.headers["retry-after"])
                except (ValueError, TypeError):
                    pass
            return True, "rate_limit", retry_after
        if status_code in settings.failover_eligible_status_codes:
            return True, "provider_server_error", None
        return False, "ineligible_http_status", None

    # 4. Connection / Network Failures (Eligible before/during upstream call)
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return True, "connection_failure", None

    # 5. Upstream Provider 5xx Errors (Eligible)
    if isinstance(exc, ProviderError):
        status_code = getattr(exc, "status_code", 502)
        error_code = getattr(exc, "error_code", "provider_error")
        if (
            status_code in settings.failover_eligible_status_codes
            or error_code in settings.failover_eligible_error_codes
        ):
            return True, "provider_server_error", getattr(exc, "retry_after", None)
        return False, "unclassified_provider_error", None

    if isinstance(exc, ProviderMalformedResponseError):
        return True, "malformed_response", None

    # 6. General AppException check against eligible status/error codes
    if isinstance(exc, AppException):
        if (
            exc.status_code in settings.failover_eligible_status_codes
            or exc.error_code in settings.failover_eligible_error_codes
        ):
            return True, "transient_app_error", None
        return False, "ineligible_app_error", None

    # 7. Unclassified unexpected exceptions default to ineligible
    return False, "unknown_unclassified", None


def validate_fallback_model(
    model: str,
    settings: Settings,
    catalog: Optional[Dict[str, Any]] = None,
    requested_model: Optional[str] = None,
    requires_tools: bool = False,
    requires_streaming: bool = False,
) -> Tuple[bool, str]:
    """Validate that a fallback model is allowed, approved, not retired, and safe for the environment.

    Returns:
        (is_valid, reason)
    """
    if not model or not isinstance(model, str) or not model.strip():
        return False, "Model identifier is empty."

    cleaned_model = model.strip()

    # 1. Must be in allowed_models
    if cleaned_model not in settings.allowed_models:
        return False, f"Model '{cleaned_model}' is not in allowed_models allowlist."

    # 2. Check model lifecycle status in pricing catalog
    models_catalog = catalog if catalog is not None else pricing_engine.models
    model_meta = models_catalog.get(cleaned_model)
    if model_meta:
        status = str(model_meta.get("status", "active")).lower().strip()
        if status in ("retired", "deprecated"):
            return (
                False,
                f"Model '{cleaned_model}' is retired or deprecated (status: {status}).",
            )
        if status == "reference_unsupported":
            return (
                False,
                f"Model '{cleaned_model}' is a reference catalog entry without an implemented provider adapter.",
            )
        if status == "restricted_legacy" and not getattr(settings, "allow_restricted_models", False):
            return (
                False,
                f"Model '{cleaned_model}' is a restricted legacy model and ALLOW_RESTRICTED_MODELS is false.",
            )

    # 3. Mock fallback safety restriction
    is_candidate_mock = cleaned_model.startswith("mock-") or (
        model_meta is not None and model_meta.get("provider") == "mock"
    )
    is_requested_mock = False
    if requested_model:
        req_meta = models_catalog.get(requested_model)
        is_requested_mock = requested_model.startswith("mock-") or (
            req_meta is not None and req_meta.get("provider") == "mock"
        )

    if is_candidate_mock and not is_requested_mock:
        is_production = settings.app_env.lower().strip() in ("production", "prod")
        if is_production:
            return (
                False,
                f"Mock model '{cleaned_model}' cannot serve as fallback for real model '{requested_model}' in production.",
            )
        if not settings.failover_allow_mock_fallback:
            return (
                False,
                f"Mock model '{cleaned_model}' is rejected as fallback for '{requested_model}' because FAILOVER_ALLOW_MOCK_FALLBACK is false.",
            )

    # 4. Tool calling support requirement
    if requires_tools and not model_supports_tools(cleaned_model):
        return (
            False,
            f"Model '{cleaned_model}' does not support tool calling required by the request.",
        )

    # 5. Streaming support requirement
    if requires_streaming and not model_supports_streaming(cleaned_model):
        return (
            False,
            f"Model '{cleaned_model}' does not support streaming required by the request.",
        )

    # 6. Combined streaming tool calling requirement
    if requires_tools and requires_streaming and not model_supports_streaming_tools(cleaned_model):
        return (
            False,
            f"Model '{cleaned_model}' does not support streaming tool calling required by the request.",
        )

    return True, "valid"


async def execute_with_failover(
    request: ChatCompletionRequest,
    settings: Settings,
    allow_failover: bool,
    provider_resolver: Callable[[str, Settings], BaseLLMProvider],
    overall_start_time: float,
) -> FailoverExecutionResult:
    """Execute chat completion with deterministic multi-provider failover."""
    attempts: List[FailoverAttempt] = []

    # 1. Build ordered candidate list
    candidate_models: List[str] = [request.model]

    if allow_failover:
        requires_tools = bool(request.tools and request.tool_choice != "none")
        raw_fallbacks = settings.get_fallback_models_for(request.model)
        for fb_model in raw_fallbacks:
            if fb_model == request.model:
                continue
            is_valid, reason = validate_fallback_model(
                fb_model,
                settings,
                requested_model=request.model,
                requires_tools=requires_tools,
                requires_streaming=False,
            )
            if is_valid:
                if fb_model not in candidate_models:
                    candidate_models.append(fb_model)
            else:
                logger.warning(
                    f"Skipping fallback candidate '{fb_model}' for '{request.model}': {reason}"
                )

    max_attempts = settings.failover_max_attempts if allow_failover else 1
    timeout_budget = settings.failover_timeout_budget_seconds

    last_error: Optional[Exception] = None

    # 2. Iterate through candidate attempts
    for attempt_idx, candidate_model in enumerate(candidate_models):
        if attempt_idx >= max_attempts:
            logger.info(
                f"Maximum attempt limit ({max_attempts}) reached for request. Halting failover."
            )
            break

        elapsed = time.perf_counter() - overall_start_time
        remaining_budget = timeout_budget - elapsed
        if remaining_budget <= 0.05:
            logger.warning(
                f"Failover request deadline reached ({timeout_budget}s budget exhausted). Halting failover."
            )
            if last_error is None:
                last_error = ProviderTimeoutError(
                    f"Overall request timeout budget of {timeout_budget}s exceeded."
                )
            break

        attempt_timeout = min(settings.provider_timeout_seconds, remaining_budget)
        provider = provider_resolver(candidate_model, settings)
        provider_name = provider.name

        attempt_num = attempt_idx + 1
        cloned_request = request.model_copy(update={"model": candidate_model})

        attempt_start = time.perf_counter()
        try:
            logger.info(
                f"Attempting completion {attempt_num}/{min(max_attempts, len(candidate_models))} "
                f"using provider '{provider_name}' and model '{candidate_model}'"
            )
            response = await asyncio.wait_for(
                provider.complete(cloned_request),
                timeout=attempt_timeout,
            )
            latency_ms = round((time.perf_counter() - attempt_start) * 1000, 2)

            # Ensure response model reflects candidate or actual model
            actual_model = response.model or candidate_model

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_provider_latency(provider_name, actual_model, latency_ms / 1000.0)
                except Exception:
                    pass

            attempts.append(
                FailoverAttempt(
                    attempt_number=attempt_num,
                    provider=provider_name,
                    model=actual_model,
                    success=True,
                    latency_ms=latency_ms,
                )
            )

            return FailoverExecutionResult(
                response=response,
                serving_provider=provider_name,
                serving_model=actual_model,
                attempts=attempts,
                failover_occurred=(attempt_idx > 0),
                last_error=None,
            )

        except asyncio.TimeoutError as timeout_exc:
            latency_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
            timeout_err = ProviderTimeoutError(
                f"Provider '{provider_name}' timed out after {attempt_timeout:.1f}s."
            )
            last_error = timeout_err
            is_eligible, cat, retry_hint = classify_failure(timeout_err, settings)

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    m = get_metrics()
                    m.record_provider_latency(provider_name, candidate_model, latency_ms / 1000.0)
                    m.record_provider_error(provider_name, "timeout")
                except Exception:
                    pass

            attempts.append(
                FailoverAttempt(
                    attempt_number=attempt_num,
                    provider=provider_name,
                    model=candidate_model,
                    success=False,
                    latency_ms=latency_ms,
                    error_code=timeout_err.error_code,
                    error_message=timeout_err.message,
                    failure_category=cat,
                    retry_after=retry_hint,
                )
            )

            has_more = (
                allow_failover
                and (attempt_num < max_attempts)
                and (attempt_idx + 1 < len(candidate_models))
            )
            if not has_more:
                break

        except Exception as exc:
            latency_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
            last_error = exc
            is_eligible, cat, retry_hint = classify_failure(exc, settings)

            err_code = getattr(exc, "error_code", type(exc).__name__)
            err_msg = getattr(exc, "message", str(exc))

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    m = get_metrics()
                    m.record_provider_latency(provider_name, candidate_model, latency_ms / 1000.0)
                    m.record_provider_error(provider_name, cat or err_code)
                except Exception:
                    pass

            attempts.append(
                FailoverAttempt(
                    attempt_number=attempt_num,
                    provider=provider_name,
                    model=candidate_model,
                    success=False,
                    latency_ms=latency_ms,
                    error_code=err_code,
                    error_message=err_msg,
                    failure_category=cat,
                    retry_after=retry_hint,
                )
            )

            has_more = (
                allow_failover
                and (attempt_num < max_attempts)
                and (attempt_idx + 1 < len(candidate_models))
            )

            # Ineligible failures stop immediately
            if not is_eligible or not has_more:
                break

            # Handle retry delay if hint provided and within budget
            if retry_hint is not None and retry_hint > 0:
                cur_elapsed = time.perf_counter() - overall_start_time
                rem = timeout_budget - cur_elapsed
                if retry_hint <= settings.failover_max_retry_delay_seconds and retry_hint < rem:
                    logger.info(
                        f"Respecting upstream Retry-After hint: waiting {retry_hint}s before fallback attempt"
                    )
                    await asyncio.sleep(retry_hint)
                else:
                    logger.warning(
                        f"Retry-After hint of {retry_hint}s exceeds budget or cap; skipping delay"
                    )
            elif settings.failover_retry_delay_seconds > 0:
                cur_elapsed = time.perf_counter() - overall_start_time
                rem = timeout_budget - cur_elapsed
                delay = min(settings.failover_retry_delay_seconds, max(0.0, rem - 0.2))
                if delay > 0.05:
                    await asyncio.sleep(delay)

    # All attempts exhausted or stopped due to ineligible error
    last_provider = attempts[-1].provider if attempts else "gateway"
    last_model = attempts[-1].model if attempts else request.model

    return FailoverExecutionResult(
        response=None,
        serving_provider=last_provider,
        serving_model=last_model,
        attempts=attempts,
        failover_occurred=len(attempts) > 1,
        last_error=last_error or ProviderError("All providers failed to complete request."),
    )


async def init_stream_with_failover(
    request: ChatCompletionRequest,
    settings: Settings,
    allow_failover: bool,
    provider_resolver: Callable[[str, Settings], BaseLLMProvider],
    overall_start_time: float,
) -> StreamingFailoverInitResult:
    """Resolve primary or fallback provider before emitting the first streaming chunk.

    Guarantees:
    - Pre-stream failures can failover to configured fallbacks.
    - Once the first chunk is obtained and returned, failover halts and the stream commits.
    - If all candidates fail or failover is disallowed/ineligible, the terminal exception is raised.
    """
    attempts: List[FailoverAttempt] = []

    # 1. Build ordered candidate list
    candidate_models: List[str] = [request.model]

    if allow_failover:
        requires_tools = bool(request.tools and request.tool_choice != "none")
        raw_fallbacks = settings.get_fallback_models_for(request.model)
        for fb_model in raw_fallbacks:
            if fb_model == request.model:
                continue
            is_valid, reason = validate_fallback_model(
                fb_model,
                settings,
                requested_model=request.model,
                requires_tools=requires_tools,
                requires_streaming=True,
            )
            if is_valid:
                if fb_model not in candidate_models:
                    candidate_models.append(fb_model)
            else:
                logger.warning(
                    f"Skipping fallback candidate '{fb_model}' for '{request.model}': {reason}"
                )

    max_attempts = settings.failover_max_attempts if allow_failover else 1
    timeout_budget = settings.failover_timeout_budget_seconds

    last_error: Optional[Exception] = None

    for attempt_idx, candidate_model in enumerate(candidate_models):
        if attempt_idx >= max_attempts:
            logger.info(
                f"Maximum attempt limit ({max_attempts}) reached for streaming request. Halting failover."
            )
            break

        elapsed = time.perf_counter() - overall_start_time
        remaining_budget = timeout_budget - elapsed
        if remaining_budget <= 0.05:
            logger.warning(
                f"Failover request deadline reached ({timeout_budget}s budget exhausted). Halting failover."
            )
            if last_error is None:
                last_error = ProviderTimeoutError(
                    f"Overall request timeout budget of {timeout_budget}s exceeded."
                )
            break

        attempt_timeout = min(settings.provider_timeout_seconds, remaining_budget)
        provider = provider_resolver(candidate_model, settings)
        provider_name = provider.name

        attempt_num = attempt_idx + 1
        cloned_request = request.model_copy(update={"model": candidate_model})

        attempt_start = time.perf_counter()
        gen = provider.stream_complete(cloned_request)

        try:
            logger.info(
                f"Attempting streaming connection {attempt_num}/{min(max_attempts, len(candidate_models))} "
                f"using provider '{provider_name}' and model '{candidate_model}'"
            )
            # Obtain the first chunk to verify stream initialization before committing
            first_chunk: Optional[ChatCompletionChunk] = None
            try:
                first_chunk = await asyncio.wait_for(
                    gen.__anext__(),
                    timeout=attempt_timeout,
                )
            except StopAsyncIteration:
                first_chunk = ChatCompletionChunk(
                    id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    created=int(time.time()),
                    model=candidate_model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(role="assistant", content=""),
                            finish_reason="stop",
                        )
                    ],
                )

            latency_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
            actual_model = first_chunk.model or candidate_model

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    get_metrics().record_provider_latency(provider_name, actual_model, latency_ms / 1000.0)
                except Exception:
                    pass

            attempts.append(
                FailoverAttempt(
                    attempt_number=attempt_num,
                    provider=provider_name,
                    model=actual_model,
                    success=True,
                    latency_ms=latency_ms,
                )
            )

            return StreamingFailoverInitResult(
                first_chunk=first_chunk,
                stream_generator=gen,
                serving_provider=provider_name,
                serving_model=actual_model,
                attempts=attempts,
                failover_occurred=(attempt_idx > 0),
            )

        except asyncio.TimeoutError:
            latency_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
            timeout_err = ProviderTimeoutError(
                f"Provider '{provider_name}' timed out after {attempt_timeout:.1f}s while initializing stream."
            )
            last_error = timeout_err
            is_eligible, cat, retry_hint = classify_failure(timeout_err, settings)

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    m = get_metrics()
                    m.record_provider_latency(provider_name, candidate_model, latency_ms / 1000.0)
                    m.record_provider_error(provider_name, "timeout")
                except Exception:
                    pass

            attempts.append(
                FailoverAttempt(
                    attempt_number=attempt_num,
                    provider=provider_name,
                    model=candidate_model,
                    success=False,
                    latency_ms=latency_ms,
                    error_code=timeout_err.error_code,
                    error_message=timeout_err.message,
                    failure_category=cat,
                    retry_after=retry_hint,
                )
            )

            has_more = (
                allow_failover
                and (attempt_num < max_attempts)
                and (attempt_idx + 1 < len(candidate_models))
            )
            if not has_more:
                break

        except Exception as exc:
            latency_ms = round((time.perf_counter() - attempt_start) * 1000, 2)
            last_error = exc
            is_eligible, cat, retry_hint = classify_failure(exc, settings)

            err_code = getattr(exc, "error_code", type(exc).__name__)
            err_msg = getattr(exc, "message", str(exc))

            if getattr(settings, "metrics_enabled", True):
                try:
                    from app.metrics import get_metrics
                    m = get_metrics()
                    m.record_provider_latency(provider_name, candidate_model, latency_ms / 1000.0)
                    m.record_provider_error(provider_name, cat or err_code)
                except Exception:
                    pass

            attempts.append(
                FailoverAttempt(
                    attempt_number=attempt_num,
                    provider=provider_name,
                    model=candidate_model,
                    success=False,
                    latency_ms=latency_ms,
                    error_code=err_code,
                    error_message=err_msg,
                    failure_category=cat,
                    retry_after=retry_hint,
                )
            )

            has_more = (
                allow_failover
                and (attempt_num < max_attempts)
                and (attempt_idx + 1 < len(candidate_models))
            )

            if not is_eligible or not has_more:
                break

            if retry_hint is not None and retry_hint > 0:
                cur_elapsed = time.perf_counter() - overall_start_time
                rem = timeout_budget - cur_elapsed
                if retry_hint <= settings.failover_max_retry_delay_seconds and retry_hint < rem:
                    await asyncio.sleep(retry_hint)
            elif settings.failover_retry_delay_seconds > 0:
                cur_elapsed = time.perf_counter() - overall_start_time
                rem = timeout_budget - cur_elapsed
                delay = min(settings.failover_retry_delay_seconds, max(0.0, rem - 0.2))
                if delay > 0.05:
                    await asyncio.sleep(delay)

    # All attempts exhausted
    if last_error:
        if isinstance(last_error, AppException):
            last_error.headers = {
                "X-Failover-Occurred": "true" if len(attempts) > 1 else "false",
                "X-Failover-Attempts": str(len(attempts)),
                "X-Requested-Model": request.model,
                "X-Serving-Model": attempts[-1].model if attempts else request.model,
                "X-Serving-Provider": attempts[-1].provider if attempts else "gateway",
            }
        raise last_error
    raise ProviderError("All providers failed to initialize stream.")
