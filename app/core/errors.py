"""Exception classes and error response normalization for SafeRoute LLM Gateway."""

from typing import Any, Dict, Optional
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import logger
from app.core.request_context import get_request_id


class AppException(Exception):
    """Base application exception with standardized error details."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_type: str = "invalid_request_error",
        error_code: str = "bad_request",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code
        self.headers = dict(headers) if headers else {}


class UnsupportedParameterError(AppException):
    """Raised when an unsupported parameter (e.g. stream: true, extra fields) is received."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            error_code="unsupported_parameter",
        )


class InvalidModelError(AppException):
    """Raised when the requested model is not found or not permitted."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            error_code="invalid_model",
        )


class ProviderTimeoutError(AppException):
    """Raised when upstream model provider exceeds configured timeout."""

    def __init__(self, message: str = "Upstream model provider timed out.") -> None:
        super().__init__(
            message=message,
            status_code=504,
            error_type="gateway_timeout_error",
            error_code="gateway_timeout",
        )


class ProviderError(AppException):
    """Raised when upstream model provider experiences an internal outage or failure."""

    def __init__(self, message: str = "Upstream model provider returned an error.") -> None:
        super().__init__(
            message=message,
            status_code=502,
            error_type="bad_gateway_error",
            error_code="provider_error",
        )


class ProviderMalformedResponseError(AppException):
    """Raised when upstream provider returns an invalid or unparseable response."""

    def __init__(self, message: str = "Upstream provider returned a malformed response.") -> None:
        super().__init__(
            message=message,
            status_code=502,
            error_type="bad_gateway_error",
            error_code="provider_malformed_response",
        )


class ProviderAuthenticationError(AppException):
    """Raised when upstream cloud provider rejects the gateway's API key or credentials."""

    def __init__(self, message: str = "Upstream cloud provider authentication failed.") -> None:
        super().__init__(
            message=message,
            status_code=502,
            error_type="bad_gateway_error",
            error_code="provider_authentication_error",
        )


class ProviderRateLimitError(AppException):
    """Raised when upstream cloud provider returns HTTP 429 rate limit exceeded."""

    def __init__(
        self,
        message: str = "Upstream cloud provider rate limit exceeded.",
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=502,
            error_type="bad_gateway_error",
            error_code="provider_rate_limit_error",
        )
        self.retry_after = retry_after


class ProviderUnavailableError(ProviderError):
    """Raised when upstream cloud provider returns HTTP 503 Service Unavailable / Model Overloaded."""

    def __init__(
        self,
        message: str = "Upstream cloud provider is temporarily unavailable or overloaded.",
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message=message)
        self.status_code = 503
        self.error_type = "service_unavailable_error"
        self.error_code = "service_unavailable"
        self.retry_after = retry_after
        if retry_after is not None:
            self.headers["Retry-After"] = str(
                int(retry_after) if isinstance(retry_after, (int, float)) and float(retry_after).is_integer() else retry_after
            )


class PayloadTooLargeError(AppException):
    """Raised when request payload exceeds configured size limit."""

    def __init__(self, message: str = "Request payload exceeds maximum allowed size.") -> None:
        super().__init__(
            message=message,
            status_code=413,
            error_type="invalid_request_error",
            error_code="payload_too_large",
        )


class AuthenticationError(AppException):
    """Raised when client API key is missing, invalid, or revoked."""

    def __init__(self, message: str = "Invalid or missing authentication credentials.") -> None:
        super().__init__(
            message=message,
            status_code=401,
            error_type="authentication_error",
            error_code="invalid_api_key",
        )


class DatabaseError(AppException):
    """Raised when a database transaction or operation fails in strict mode."""

    def __init__(self, message: str = "Database operation failed.") -> None:
        super().__init__(
            message=message,
            status_code=500,
            error_type="internal_server_error",
            error_code="database_error",
        )


class RateLimitExceededError(AppException):
    """Raised when client exceeds configured rate limit quota."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please retry after the indicated interval.",
        retry_after: int = 1,
        limit: int = 60,
        remaining: int = 0,
        reset: int = 1,
    ) -> None:
        super().__init__(
            message=message,
            status_code=429,
            error_type="requests",
            error_code="rate_limit_exceeded",
        )
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining
        self.reset = reset


class RateLimiterUnavailableError(AppException):
    """Raised when rate limiter backend fails under fail_closed security policy."""

    def __init__(
        self,
        message: str = "Rate limit verification service unavailable. Request rejected per security policy.",
    ) -> None:
        super().__init__(
            message=message,
            status_code=503,
            error_type="service_unavailable_error",
            error_code="rate_limiter_unavailable",
        )


class InputGuardrailBlockedError(AppException):
    """Raised when incoming user prompt content violates input guardrail rules."""

    def __init__(
        self,
        message: str = "Request content was blocked by input safety guardrails.",
        rule_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            error_code="input_guardrail_blocked",
        )
        self.rule_id = rule_id


class OutputGuardrailBlockedError(AppException):
    """Raised when model provider completion content violates output guardrail rules."""

    def __init__(
        self,
        message: str = "Provider response was blocked by output safety guardrails.",
        rule_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=502,
            error_type="bad_gateway_error",
            error_code="output_guardrail_blocked",
        )
        self.rule_id = rule_id


class SafetyClassificationBlockedError(AppException):
    """Raised when request or response violates configured semantic safety policy."""

    def __init__(
        self,
        message: str = "Request was blocked by semantic safety classification.",
        category: Optional[str] = None,
        score: Optional[float] = None,
        action: Optional[str] = "block",
        reason: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            error_code="safety_classification_blocked",
        )
        self.category = category
        self.score = score
        self.action = action
        self.reason = reason


class SafetyClassifierUnavailableError(AppException):
    """Raised when safety classification service is unavailable under fail-closed policy."""

    def __init__(
        self,
        message: str = "Semantic safety classification service is unavailable.",
    ) -> None:
        super().__init__(
            message=message,
            status_code=503,
            error_type="service_unavailable_error",
            error_code="safety_classifier_unavailable",
        )


def build_error_response(
    status_code: int,
    error_type: str,
    error_code: str,
    message: str,
    request_id: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """Format and return a standardized JSON error response."""
    rid = request_id or get_request_id()
    content = {
        "error": {
            "type": error_type,
            "code": error_code,
            "message": message,
            "request_id": rid,
        }
    }
    headers = {"X-Request-ID": rid}
    if status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if extra_headers:
        headers.update(extra_headers)

    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=headers,
    )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handler for custom application exceptions."""
    rid = get_request_id()
    logger.warning(
        f"Application error: {exc.error_code} - {exc.message}",
        extra={"extra_data": {"status_code": exc.status_code, "error_code": exc.error_code}},
    )
    extra_headers: Dict[str, str] = {}
    if getattr(exc, "headers", None):
        extra_headers.update(exc.headers)
    if isinstance(exc, RateLimitExceededError):
        extra_headers["Retry-After"] = str(exc.retry_after)
        extra_headers["X-RateLimit-Limit"] = str(exc.limit)
        extra_headers["X-RateLimit-Remaining"] = str(exc.remaining)
        extra_headers["X-RateLimit-Reset"] = str(exc.reset)

    return build_error_response(
        status_code=exc.status_code,
        error_type=exc.error_type,
        error_code=exc.error_code,
        message=exc.message,
        request_id=rid,
        extra_headers=extra_headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic validation errors, distinguishing unsupported fields from schema errors."""
    rid = get_request_id()
    errors = exc.errors()

    # Check if any error is due to extra forbidden fields
    extra_field_errors = [err for err in errors if err.get("type") == "extra_forbidden"]
    if extra_field_errors:
        field_names = [str(err.get("loc", ["unknown"])[-1]) for err in extra_field_errors]
        message = f"Unsupported parameter(s): {', '.join(field_names)}. Extra fields are not supported."
        logger.warning(f"Unsupported parameter validation error: {message}")
        return build_error_response(
            status_code=400,
            error_type="invalid_request_error",
            error_code="unsupported_parameter",
            message=message,
            request_id=rid,
        )

    # Check if any error is due to streaming being requested
    stream_errors = [
        err for err in errors
        if "stream" in [str(l).lower() for l in err.get("loc", [])]
        or "streaming" in str(err.get("msg", "")).lower()
    ]
    if stream_errors:
        message = "Streaming is not supported in Phase 1."
        logger.warning(f"Streaming unsupported error: {message}")
        return build_error_response(
            status_code=400,
            error_type="invalid_request_error",
            error_code="unsupported_parameter",
            message=message,
            request_id=rid,
        )

    # Compile clear message for ordinary schema validation errors
    messages = []
    for err in errors:
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        messages.append(f"{loc}: {msg}" if loc else msg)

    combined_message = "; ".join(messages)
    logger.warning(f"Schema validation error: {combined_message}")
    return build_error_response(
        status_code=422,
        error_type="invalid_request_error",
        error_code="validation_error",
        message=combined_message,
        request_id=rid,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions, hiding stack traces from clients."""
    rid = get_request_id()
    logger.error(
        f"Unhandled exception during request processing: {str(exc)}",
        exc_info=True,
    )
    return build_error_response(
        status_code=500,
        error_type="internal_server_error",
        error_code="internal_error",
        message="An internal server error occurred.",
        request_id=rid,
    )
