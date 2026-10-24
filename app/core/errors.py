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
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code


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


class PayloadTooLargeError(AppException):
    """Raised when request payload exceeds configured size limit."""

    def __init__(self, message: str = "Request payload exceeds maximum allowed size.") -> None:
        super().__init__(
            message=message,
            status_code=413,
            error_type="invalid_request_error",
            error_code="payload_too_large",
        )


def build_error_response(
    status_code: int,
    error_type: str,
    error_code: str,
    message: str,
    request_id: Optional[str] = None,
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
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"X-Request-ID": rid},
    )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handler for custom application exceptions."""
    rid = get_request_id()
    logger.warning(
        f"Application error: {exc.error_code} - {exc.message}",
        extra={"extra_data": {"status_code": exc.status_code, "error_code": exc.error_code}},
    )
    return build_error_response(
        status_code=exc.status_code,
        error_type=exc.error_type,
        error_code=exc.error_code,
        message=exc.message,
        request_id=rid,
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
