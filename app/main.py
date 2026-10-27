"""FastAPI Application entry point for SafeRoute LLM Gateway."""

import time
from typing import Optional
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.config import Settings, get_settings
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
        settings = getattr(request.app.state, "settings", None) or get_settings()
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_size_bytes:
                    rid = set_request_id(request.headers.get("x-request-id"))
                    resp = build_error_response(
                        status_code=413,
                        error_type="invalid_request_error",
                        error_code="payload_too_large",
                        message=f"Request size exceeds maximum limit of {settings.max_request_size_bytes} bytes.",
                        request_id=rid,
                    )
                    resp.headers["X-Request-ID"] = rid
                    resp.headers["X-Content-Type-Options"] = "nosniff"
                    resp.headers["X-Frame-Options"] = "DENY"
                    if getattr(settings, "metrics_enabled", True):
                        try:
                            from app.metrics import get_metrics
                            m = get_metrics()
                            m.record_http_request(
                                route=request.url.path,
                                status=413,
                                provider="gateway",
                                duration_seconds=0.0,
                            )
                            m.record_guardrail_block(stage="input", detector="payload_size")
                        except Exception:
                            pass
                    return resp
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

        # 3. Attach Request ID and defensive security headers to response
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"

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

        # 5. Record Prometheus metrics
        if getattr(settings, "metrics_enabled", True):
            try:
                from app.metrics import get_metrics
                provider = response.headers.get("X-Serving-Provider", "gateway")
                get_metrics().record_http_request(
                    route=request.url.path,
                    status=response.status_code,
                    provider=provider,
                    duration_seconds=max(0.0, duration_ms / 1000.0),
                )
            except Exception:
                pass

        return response


from contextlib import asynccontextmanager
from app.providers import shutdown_providers
from app.cache import shutdown_cache
from app.limiter import shutdown_limiter
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan resources."""
    import asyncio
    if get_settings in app.dependency_overrides:
        settings = app.dependency_overrides[get_settings]()
    else:
        settings = getattr(app.state, "settings", None) or get_settings()

    # 1. Initialize SQLite / relational database tables
    from app.db.session import get_engine
    engine = get_engine(settings.database_url)
    await asyncio.to_thread(init_db, engine)


    # 2. Pre-warm local safety classifier if enabled to eliminate request-path cold start
    if getattr(settings, "safety_classifier_enabled", False):
        if getattr(settings, "safety_classifier_provider", "local") == "local":
            try:
                from app.guardrails.classifier import get_safety_classifier
                clf = get_safety_classifier(settings)
                if hasattr(clf, "_ensure_loaded"):
                    await clf._ensure_loaded()
                    logger.info("Safety classifier model pre-warmed successfully at startup.")
            except Exception as exc:
                logger.error(f"Failed to pre-warm safety classifier at startup: {exc}")
                if getattr(settings, "safety_classifier_failure_policy", "fail_closed") == "fail_closed" and getattr(settings, "app_env", "") in ("production", "prod"):
                    raise

    # 3. Pre-warm semantic cache embedding model if enabled
    if getattr(settings, "semantic_cache_enabled", False):
        if getattr(settings, "semantic_cache_embedding_provider", "local") == "local":
            try:
                from app.cache.semantic_cache import get_semantic_cache
                sem_cache = get_semantic_cache(settings)
                emb_prov = sem_cache._get_embedding_provider()
                if hasattr(emb_prov, "_sync_init_model"):
                    await asyncio.to_thread(emb_prov._sync_init_model)
                    logger.info("Semantic cache embedding model pre-warmed successfully at startup.")
            except Exception as exc:
                logger.warning(f"Failed to pre-warm semantic cache embedding model at startup: {exc}")

    yield

    # 4. Graceful shutdown of connections and thread pools
    await shutdown_providers()
    await shutdown_cache()
    await shutdown_limiter()
    try:
        from app.cache.semantic_cache import get_semantic_cache
        sem_cache = get_semantic_cache(settings)
        if hasattr(sem_cache, "close"):
            await sem_cache.close()
    except Exception as exc:
        logger.warning(f"Error during semantic cache shutdown: {exc}")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    cfg = settings or get_settings()
    setup_logging(cfg.log_level)

    app = FastAPI(
        title="SafeRoute LLM Gateway",
        description="A reliable, resilient LLM Gateway foundation with OpenAI-compatible API.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    # Register CORS middleware
    origins = cfg.cors_allowed_origins
    allow_credentials = False if "*" in origins else True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-Cache",
            "X-Cache-Status",
            "X-Cache-Key",
            "X-Cache-Similarity",
            "X-Serving-Provider",
            "X-Serving-Model",
            "X-Requested-Model",
            "X-Failover-Occurred",
            "X-Failover-Attempts",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "X-Safety-Risk",
            "Retry-After",
        ],
    )

    # Register custom middleware
    app.add_middleware(RequestTrackingMiddleware)

    # Register error handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # Include API routes
    app.include_router(router)
    from app.api.management import management_router
    app.include_router(management_router)

    return app


app = create_app()
