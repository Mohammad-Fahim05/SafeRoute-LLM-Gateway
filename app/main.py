"""FastAPI Application entry point for SafeRoute LLM Gateway."""

import time
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.config import get_settings
from app.core.errors import (
    AppException,
    PayloadTooLargeError,
    app_exception_handler,
    build_error_response,
    generic_exception_handler,
    validation_exception_handler,
)
from app.core.logging import logger, setup_logging
from app.core.request_context import get_request_id, set_request_id


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware that injects request IDs, measures latency, and produces structured access logs."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check content length limit if provided in headers
        settings = get_settings()
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_size_bytes:
                    rid = set_request_id(request.headers.get("x-request-id"))
                    return build_error_response(
                        status_code=413,
                        error_type="invalid_request_error",
                        error_code="payload_too_large",
                        message=f"Request size exceeds maximum limit of {settings.max_request_size_bytes} bytes.",
                        request_id=rid,
                    )
            except ValueError:
                pass

        # 1. Establish request ID
        incoming_rid = request.headers.get("x-request-id")
        rid = set_request_id(incoming_rid)

        start_time = time.perf_counter()

        # 2. Process request
        try:
            response = await call_next(request)
        except AppException as exc:
            response = await app_exception_handler(request, exc)
        except RequestValidationError as exc:
            response = await validation_exception_handler(request, exc)
        except Exception as exc:
            response = await generic_exception_handler(request, exc)
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 3. Attach Request ID to response header
        response.headers["X-Request-ID"] = rid

        # 4. Structured log for request outcome (never logging bodies or secrets)
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} ({duration_ms}ms)",
            extra={
                "extra_data": {
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else "unknown",
                }
            },
        )

        return response


from contextlib import asynccontextmanager
from app.providers import shutdown_providers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan resources."""
    yield
    await shutdown_providers()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title="SafeRoute LLM Gateway",
        description="A reliable, resilient LLM Gateway foundation with OpenAI-compatible API.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Register custom middleware
    app.add_middleware(RequestTrackingMiddleware)

    # Register error handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # Include API routes
    app.include_router(router)

    return app


app = create_app()
