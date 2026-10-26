"""Management and Observability API Router for SafeRoute LLM Gateway.

Provides structured, authenticated, read-only operational telemetry,
SQLite database inspection, cache metrics, provider status, and request details
for the SafeRoute management console.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
import time
from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select, text

from app.config import Settings, get_settings
from app.core.auth import (
    get_client_auth_details,
    verify_admin_access,
    verify_api_key,
    verify_client_auth_details,
)
from app.core.logging import logger
from app.db.models import ApiKeyAudit, Client, RequestRecord, UsageRecord
from app.db.session import get_db_session, get_engine
from app.providers.capabilities import MODEL_CAPABILITIES

management_router = APIRouter(prefix="/api/management", tags=["management"])

# Whitelist of tables permitted for read-only inspection
ALLOWED_INSPECTION_TABLES = {
    "clients": Client,
    "request_records": RequestRecord,
    "usage_records": UsageRecord,
    "api_key_audits": ApiKeyAudit,
}


# ------------------------------------------------------------------------------
# Auth Status & Key Verification
# ------------------------------------------------------------------------------

@management_router.get("/auth/status")
async def get_auth_status(settings: Settings = Depends(get_settings)) -> Dict[str, Any]:
    """Return whether authentication is required and configured."""
    return {
        "auth_enabled": settings.auth_enabled,
        "key_prefix": "gw_test_",
        "registered_clients_count": len(settings.client_keys),
    }


class VerifyKeyRequest(BaseModel):
    api_key: str


@management_router.post("/auth/verify")
async def verify_management_key(
    payload: VerifyKeyRequest,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """Validate a client API key and return identified client metadata."""
    if not settings.auth_enabled:
        return {
            "valid": True,
            "client_id": "anonymous_dev",
            "role": "admin",
            "is_admin": True,
            "auth_enabled": False,
        }

    raw_key = payload.api_key.strip()
    if raw_key.lower().startswith("bearer "):
        raw_key = raw_key[7:].strip()

    try:
        details = get_client_auth_details(raw_key, settings)
        if not details.get("enabled"):
            return {"valid": False, "error": "Client key is revoked or disabled."}
        return {
            "valid": True,
            "client_id": details["client_id"],
            "role": details.get("role", "client"),
            "is_admin": details.get("is_admin", False),
            "auth_enabled": True,
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}



# ------------------------------------------------------------------------------
# Overview & Operational Telemetry
# ------------------------------------------------------------------------------

@management_router.get("/overview")
async def get_overview_telemetry(
    settings: Settings = Depends(get_settings),
    auth_details: Dict[str, Any] = Depends(verify_client_auth_details),
) -> Dict[str, Any]:
    """Compute comprehensive operational KPI metrics from durable SQLite request records."""
    engine = get_engine(settings.database_url)
    is_admin = auth_details.get("is_admin", False)
    client_id = auth_details.get("client_id")
    client_filter = [RequestRecord.client_id == client_id] if not is_admin else []

    with get_db_session(engine) as session:
        # 1. Total, success, and failed counts
        total_stmt = select(func.count(RequestRecord.id))
        if client_filter:
            total_stmt = total_stmt.where(*client_filter)
        total_requests = session.scalar(total_stmt) or 0

        success_stmt = select(func.count(RequestRecord.id)).where(RequestRecord.status == "success")
        if client_filter:
            success_stmt = success_stmt.where(*client_filter)
        successful_requests = session.scalar(success_stmt) or 0

        failed_requests = total_requests - successful_requests
        success_rate = round((successful_requests / total_requests * 100), 2) if total_requests > 0 else 100.0

        # 2. Latency percentiles & averages
        durations_stmt = (
            select(RequestRecord.duration_ms)
            .where(RequestRecord.duration_ms.isnot(None))
        )
        if client_filter:
            durations_stmt = durations_stmt.where(*client_filter)
        durations_stmt = durations_stmt.order_by(RequestRecord.duration_ms.asc())
        durations = session.scalars(durations_stmt).all()

        avg_duration = round(sum(durations) / len(durations), 2) if durations else 0.0
        p50_duration = round(durations[int(len(durations) * 0.50)], 2) if durations else 0.0
        p95_duration = round(durations[min(int(len(durations) * 0.95), len(durations) - 1)], 2) if durations else 0.0
        p99_duration = round(durations[min(int(len(durations) * 0.99), len(durations) - 1)], 2) if durations else 0.0

        # 3. Cache activity
        exact_hits_stmt = select(func.count(RequestRecord.id)).where(RequestRecord.cache_status.in_(["hit", "exact_hit"]))
        if client_filter:
            exact_hits_stmt = exact_hits_stmt.where(*client_filter)
        exact_hits = session.scalar(exact_hits_stmt) or 0

        semantic_hits_stmt = select(func.count(RequestRecord.id)).where(RequestRecord.cache_status == "semantic_hit")
        if client_filter:
            semantic_hits_stmt = semantic_hits_stmt.where(*client_filter)
        semantic_hits = session.scalar(semantic_hits_stmt) or 0
        total_cache_hits = exact_hits + semantic_hits

        cache_misses_stmt = select(func.count(RequestRecord.id)).where(RequestRecord.cache_status.in_(["miss", "exact_miss", "semantic_miss"]))
        if client_filter:
            cache_misses_stmt = cache_misses_stmt.where(*client_filter)
        cache_misses = session.scalar(cache_misses_stmt) or 0

        eligible_requests = total_cache_hits + cache_misses
        cache_hit_rate = round((total_cache_hits / eligible_requests * 100), 2) if eligible_requests > 0 else 0.0

        # 4. Token aggregates from UsageRecord joined with RequestRecord
        tokens_stmt = (
            select(
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_cost), 0),
            )
            .select_from(RequestRecord)
            .outerjoin(UsageRecord, RequestRecord.id == UsageRecord.request_record_id)
        )
        if client_filter:
            tokens_stmt = tokens_stmt.where(*client_filter)
        in_tok, out_tok, tot_tok, cost_sum = session.execute(tokens_stmt).one()

        # 5. Breakdown by provider
        prov_stmt = select(RequestRecord.provider, func.count(RequestRecord.id))
        if client_filter:
            prov_stmt = prov_stmt.where(*client_filter)
        prov_stmt = prov_stmt.group_by(RequestRecord.provider)
        provider_counts = dict(session.execute(prov_stmt).all())

        # 6. Breakdown by model
        model_stmt = select(RequestRecord.model_requested, func.count(RequestRecord.id))
        if client_filter:
            model_stmt = model_stmt.where(*client_filter)
        model_stmt = (
            model_stmt.group_by(RequestRecord.model_requested)
            .order_by(desc(func.count(RequestRecord.id)))
            .limit(10)
        )
        model_counts = dict(session.execute(model_stmt).all())

        # 7. Breakdown by HTTP status
        status_stmt = select(RequestRecord.http_status, func.count(RequestRecord.id))
        if client_filter:
            status_stmt = status_stmt.where(*client_filter)
        status_stmt = status_stmt.group_by(RequestRecord.http_status)
        http_status_counts = {str(code): cnt for code, cnt in session.execute(status_stmt).all()}

        # 8. Timeline (grouped by day)
        timeline_stmt = text(
            """
            SELECT
                DATE(created_at) as day,
                COUNT(id) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN cache_status IN ('hit', 'exact_hit', 'semantic_hit') THEN 1 ELSE 0 END) as cache_hits,
                ROUND(AVG(duration_ms), 2) as avg_duration
            FROM request_records
            WHERE (:client_id IS NULL OR client_id = :client_id)
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) ASC
            LIMIT 30
            """
        )
        timeline_rows = session.execute(
            timeline_stmt, {"client_id": None if is_admin else client_id}
        ).fetchall()
        timeline = [
            {
                "date": str(row[0]),
                "total": int(row[1]),
                "success": int(row[2]),
                "failed": int(row[3]),
                "cache_hits": int(row[4]),
                "avg_duration": float(row[5] or 0.0),
            }
            for row in timeline_rows
        ]

        # 9. Recent 5 requests
        recent_stmt = select(RequestRecord)
        if client_filter:
            recent_stmt = recent_stmt.where(*client_filter)
        recent_stmt = recent_stmt.order_by(RequestRecord.created_at.desc()).limit(5)
        recent_records = session.scalars(recent_stmt).all()
        recent_items = [
            {
                "request_id": r.request_id,
                "client_id": r.client_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "model": r.model_requested,
                "provider": r.provider,
                "http_status": r.http_status,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "cache_status": r.cache_status,
                "stream": bool(r.stream),
                "failover_occurred": bool(r.failover_occurred),
            }
            for r in recent_records
        ]

    return {
        "total_requests": total_requests,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration,
        "p50_duration_ms": p50_duration,
        "p95_duration_ms": p95_duration,
        "p99_duration_ms": p99_duration,
        "exact_cache_hits": exact_hits,
        "semantic_cache_hits": semantic_hits,
        "total_cache_hits": total_cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate": cache_hit_rate,
        "total_input_tokens": int(in_tok),
        "total_output_tokens": int(out_tok),
        "total_tokens": int(tot_tok),
        "estimated_total_cost": round(float(cost_sum), 6),
        "provider_counts": provider_counts,
        "model_counts": model_counts,
        "status_counts": http_status_counts,
        "timeline": timeline,
        "recent_requests": recent_items,
    }



# ------------------------------------------------------------------------------
# Request Explorer & Details
# ------------------------------------------------------------------------------

@management_router.get("/requests")
async def list_request_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    cache_status: Optional[str] = Query(None),
    error_only: bool = Query(False),
    stream: Optional[bool] = Query(None),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
    settings: Settings = Depends(get_settings),
    auth_details: Dict[str, Any] = Depends(verify_client_auth_details),
) -> Dict[str, Any]:
    """Retrieve paginated, filterable, sortable list of request records joined with token usage."""
    engine = get_engine(settings.database_url)
    is_admin = auth_details.get("is_admin", False)
    client_id = auth_details.get("client_id")

    with get_db_session(engine) as session:
        # Base query with joined usage record
        stmt = select(RequestRecord).outerjoin(UsageRecord, RequestRecord.id == UsageRecord.request_record_id)

        # Enforce client isolation for regular (non-admin) clients
        if not is_admin:
            stmt = stmt.where(RequestRecord.client_id == client_id)

        # Filters
        if search:
            s_clean = search.strip()
            stmt = stmt.where(
                or_(
                    RequestRecord.request_id.contains(s_clean),
                    RequestRecord.model_requested.contains(s_clean),
                    RequestRecord.client_id.contains(s_clean),
                    RequestRecord.error_code.contains(s_clean),
                )
            )


        if status:
            stmt = stmt.where(RequestRecord.status == status.strip().lower())

        if provider:
            stmt = stmt.where(RequestRecord.provider == provider.strip().lower())

        if model:
            stmt = stmt.where(RequestRecord.model_requested == model.strip())

        if cache_status:
            stmt = stmt.where(RequestRecord.cache_status == cache_status.strip().lower())

        if error_only:
            stmt = stmt.where(RequestRecord.status == "failed")

        if stream is not None:
            stmt = stmt.where(RequestRecord.stream == stream)

        # Count total matching rows
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_rows = session.scalar(count_stmt) or 0

        # Sorting
        sort_column = RequestRecord.created_at
        if sort_by == "duration_ms":
            sort_column = RequestRecord.duration_ms
        elif sort_by == "http_status":
            sort_column = RequestRecord.http_status

        if sort_dir.lower() == "asc":
            stmt = stmt.order_by(sort_column.asc())
        else:
            stmt = stmt.order_by(sort_column.desc())

        # Pagination
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        records = session.scalars(stmt).all()
        total_pages = max(1, (total_rows + page_size - 1) // page_size)

        items = []
        for r in records:
            usage = r.usage
            items.append({
                "id": r.id,
                "request_id": r.request_id,
                "client_id": r.client_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "model_requested": r.model_requested,
                "model_actual": r.model_actual,
                "provider": r.provider,
                "http_status": r.http_status,
                "status": r.status,
                "error_code": r.error_code,
                "error_message": r.error_message,
                "duration_ms": r.duration_ms,
                "provider_latency_ms": r.provider_latency_ms,
                "cache_status": r.cache_status,
                "attempts_count": r.attempts_count,
                "failover_occurred": bool(r.failover_occurred),
                "stream": bool(r.stream),
                "stream_status": r.stream_status,
                # Usage breakdown
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
                "usage_source": usage.usage_source if usage else "unavailable",
                "total_cost": float(usage.total_cost) if usage and usage.total_cost is not None else 0.0,
                "currency": usage.currency if usage else "USD",
                "calculation_status": usage.calculation_status if usage else "unavailable",
            })

    return {
        "items": items,
        "total": total_rows,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@management_router.get("/requests/{request_id}")
async def get_request_record_detail(
    request_id: str,
    settings: Settings = Depends(get_settings),
    auth_details: Dict[str, Any] = Depends(verify_client_auth_details),
) -> Dict[str, Any]:
    """Retrieve full durable metadata and lifecycle audit for an individual request."""
    engine = get_engine(settings.database_url)

    with get_db_session(engine) as session:
        stmt = select(RequestRecord).where(RequestRecord.request_id == request_id)
        record = session.scalar(stmt)
        if not record:
            raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found.")

        is_admin = auth_details.get("is_admin", False)
        if not is_admin and record.client_id != auth_details.get("client_id"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: request belongs to another client identity.",
            )


        # Parse attempt sequence JSON if present
        attempts = []
        if record.attempt_sequence:
            try:
                attempts = json.loads(record.attempt_sequence)
            except Exception:
                attempts = [{"raw": record.attempt_sequence}]

        usage = record.usage
        return {
            "id": record.id,
            "request_id": record.request_id,
            "client_id": record.client_id,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "model_requested": record.model_requested,
            "model_actual": record.model_actual,
            "provider": record.provider,
            "http_status": record.http_status,
            "status": record.status,
            "error_code": record.error_code,
            "error_message": record.error_message,
            "duration_ms": record.duration_ms,
            "provider_latency_ms": record.provider_latency_ms,
            "cache_status": record.cache_status,
            "token_usage_status": record.token_usage_status,
            "attempts_count": record.attempts_count,
            "failover_occurred": bool(record.failover_occurred),
            "stream": bool(record.stream),
            "stream_status": record.stream_status,
            "attempts": attempts,
            "usage": {
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
                "usage_source": usage.usage_source if usage else "unavailable",
                "is_estimate": bool(usage.is_estimate) if usage else False,
                "pricing_version": usage.pricing_version if usage else None,
                "input_cost": float(usage.input_cost) if usage and usage.input_cost is not None else 0.0,
                "output_cost": float(usage.output_cost) if usage and usage.output_cost is not None else 0.0,
                "total_cost": float(usage.total_cost) if usage and usage.total_cost is not None else 0.0,
                "currency": usage.currency if usage else "USD",
                "calculation_status": usage.calculation_status if usage else "unavailable",
            } if usage else None,
            "retention_notice": (
                "For client data privacy and security, raw user prompt messages and "
                "assistant response bodies are not persisted to SQLite database."
            ),
        }


# ------------------------------------------------------------------------------
# SQLite Database Explorer
# ------------------------------------------------------------------------------

@management_router.get("/database/overview")
async def get_database_overview(
    settings: Settings = Depends(get_settings),
    _admin: Dict[str, Any] = Depends(verify_admin_access),
) -> Dict[str, Any]:
    """Inspect SQLite schema, table row counts, PRAGMA journal modes, and file size."""
    engine = get_engine(settings.database_url)

    # Determine file size if sqlite file exists on host
    db_file_path = settings.database_url.replace("sqlite:///", "").replace("sqlite:////", "/")
    if db_file_path.startswith("./"):
        db_file_path = os.path.abspath(db_file_path)

    file_size_bytes = 0
    if os.path.exists(db_file_path):
        try:
            file_size_bytes = os.path.getsize(db_file_path)
        except Exception:
            pass

    with get_db_session(engine) as session:
        # Journal mode
        journal_mode = session.execute(text("PRAGMA journal_mode")).scalar() or "unknown"

        tables_data = []
        for table_name, model_cls in ALLOWED_INSPECTION_TABLES.items():
            row_count = session.scalar(select(func.count()).select_from(model_cls)) or 0

            # Inspect columns via PRAGMA
            cols_info = session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            columns = [
                {
                    "cid": col[0],
                    "name": col[1],
                    "type": col[2],
                    "not_null": bool(col[3]),
                    "default_value": col[4],
                    "primary_key": bool(col[5]),
                }
                for col in cols_info
            ]

            tables_data.append({
                "table_name": table_name,
                "row_count": row_count,
                "columns": columns,
            })

    return {
        "database_url": settings.database_url,
        "database_path": db_file_path,
        "file_size_bytes": file_size_bytes,
        "journal_mode": str(journal_mode).upper(),
        "tables": tables_data,
        "read_only": True,
    }


@management_router.get("/database/tables/{table_name}/records")
async def get_table_records(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    settings: Settings = Depends(get_settings),
    _admin: Dict[str, Any] = Depends(verify_admin_access),
) -> Dict[str, Any]:
    """Read-only paginated record browser for whitelisted database tables."""
    if table_name not in ALLOWED_INSPECTION_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Table '{table_name}' is not permitted for inspection. Allowed: {list(ALLOWED_INSPECTION_TABLES.keys())}",
        )

    engine = get_engine(settings.database_url)
    model_cls = ALLOWED_INSPECTION_TABLES[table_name]

    with get_db_session(engine) as session:
        # Total rows
        total_rows = session.scalar(select(func.count()).select_from(model_cls)) or 0
        total_pages = max(1, (total_rows + page_size - 1) // page_size)

        # Columns
        cols_info = session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        columns = [c[1] for c in cols_info]

        # Paginated rows
        offset = (page - 1) * page_size
        stmt = select(model_cls).order_by(model_cls.id.desc()).offset(offset).limit(page_size)
        rows = session.scalars(stmt).all()

        records = []
        for r in rows:
            row_dict = {}
            for col in columns:
                val = getattr(r, col, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                elif isinstance(val, Decimal):
                    val = float(val)
                row_dict[col] = val
            records.append(row_dict)

    return {
        "table_name": table_name,
        "columns": columns,
        "records": records,
        "total": total_rows,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ------------------------------------------------------------------------------
# Cache & Redis Observability
# ------------------------------------------------------------------------------

@management_router.get("/cache")
async def get_cache_telemetry(
    settings: Settings = Depends(get_settings),
    _auth: Dict[str, Any] = Depends(verify_client_auth_details),
) -> Dict[str, Any]:
    """Inspect Redis connection health, exact caching stats, and semantic caching state."""
    from app.cache import get_cache

    # 1. Ping Redis
    redis_connected = False
    redis_latency_ms = None
    try:
        cache_svc = get_cache(settings)
        client = await cache_svc._get_client()
        if client:
            t0 = time.perf_counter()
            await client.ping()
            redis_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            redis_connected = True
    except Exception as exc:
        logger.debug(f"Redis ping error: {exc}")

    # 2. Query exact & semantic hit counts from SQLite
    engine = get_engine(settings.database_url)
    with get_db_session(engine) as session:
        exact_hits = session.scalar(
            select(func.count(RequestRecord.id)).where(RequestRecord.cache_status.in_(["hit", "exact_hit"]))
        ) or 0
        exact_misses = session.scalar(
            select(func.count(RequestRecord.id)).where(RequestRecord.cache_status.in_(["miss", "exact_miss"]))
        ) or 0
        semantic_hits = session.scalar(
            select(func.count(RequestRecord.id)).where(RequestRecord.cache_status == "semantic_hit")
        ) or 0
        semantic_misses = session.scalar(
            select(func.count(RequestRecord.id)).where(RequestRecord.cache_status == "semantic_miss")
        ) or 0
        bypasses = session.scalar(
            select(func.count(RequestRecord.id)).where(RequestRecord.cache_status.in_(["bypass", "disabled", "not_applicable"]))
        ) or 0

    total_hits = exact_hits + semantic_hits
    total_evaluated = total_hits + exact_misses + semantic_misses
    hit_rate = round((total_hits / total_evaluated * 100), 2) if total_evaluated > 0 else 0.0

    # Sanitize Redis URL for display
    clean_redis_url = settings.redis_url
    if "@" in clean_redis_url:
        prefix, host_part = clean_redis_url.split("@", 1)
        clean_redis_url = f"redis://***:***@{host_part}"

    return {
        "redis_connected": redis_connected,
        "redis_ping_latency_ms": redis_latency_ms,
        "redis_url": clean_redis_url,
        "exact_cache": {
            "enabled": settings.cache_enabled,
            "ttl_seconds": settings.cache_ttl_seconds,
            "namespace": settings.cache_namespace,
            "failure_policy": settings.cache_failure_policy,
            "hits": exact_hits,
            "misses": exact_misses,
        },
        "semantic_cache": {
            "enabled": getattr(settings, "semantic_cache_enabled", False),
            "threshold": getattr(settings, "semantic_cache_threshold", 0.85),
            "ttl_seconds": getattr(settings, "semantic_cache_ttl_seconds", 300),
            "embedding_provider": getattr(settings, "semantic_cache_embedding_provider", "local"),
            "embedding_model": getattr(settings, "semantic_cache_embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
            "hits": semantic_hits,
            "misses": semantic_misses,
        },
        "total_cache_hits": total_hits,
        "total_cache_misses": exact_misses + semantic_misses,
        "total_bypasses": bypasses,
        "overall_hit_rate": hit_rate,
        "streaming_replay_enabled": getattr(settings, "streaming_cache_replay_enabled", True),
    }


# ------------------------------------------------------------------------------
# Provider & Routing Status
# ------------------------------------------------------------------------------

@management_router.get("/providers")
async def get_providers_status(
    settings: Settings = Depends(get_settings),
    _auth: Dict[str, Any] = Depends(verify_client_auth_details),
) -> Dict[str, Any]:
    """Inspect active AI providers (Ollama local runtime and MockProvider)."""
    ollama_online = False
    ollama_latency_ms = None
    ollama_models = []

    # Check local Ollama availability via HTTP
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            ollama_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            if resp.status_code == 200:
                ollama_online = True
                data = resp.json()
                ollama_models = [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception as exc:
        logger.debug(f"Ollama health probe note: {exc}")

    # Registered model capabilities
    capabilities_list = []
    for model_id, cap in MODEL_CAPABILITIES.items():
        if cap.provider in ("ollama", "mock"):
            capabilities_list.append({
                "model_id": cap.model_id,
                "provider": cap.provider,
                "status": cap.status,
                "supports_text": cap.supports_text,
                "supports_streaming": cap.supports_streaming,
                "supports_tools": cap.supports_tools,
                "supports_streaming_tools": cap.supports_streaming_tools,
                "evidence_level": cap.evidence_level,
                "notes": cap.notes,
            })

    return {
        "active_provider": settings.active_provider,
        "ollama": {
            "base_url": settings.ollama_base_url,
            "is_online": ollama_online,
            "ping_latency_ms": ollama_latency_ms,
            "pulled_models": ollama_models,
        },
        "mock": {
            "name": "MockProvider",
            "is_online": True,
            "status": "in_memory_ready",
            "notes": "Deterministic in-memory provider for testing, evaluation, and latency benchmarking.",
        },
        "allowed_models": settings.allowed_models,
        "default_model": getattr(settings, "default_model", "llama3.2:1b"),
        "capabilities": capabilities_list,
        "failover": {
            "enabled": settings.failover_enabled,
            "max_attempts": settings.failover_max_attempts,
            "fallback_models": settings.failover_fallback_models,
            "allow_mock_fallback": settings.failover_allow_mock_fallback,
        },
    }


# ------------------------------------------------------------------------------
# System Health & Prometheus Metrics
# ------------------------------------------------------------------------------

@management_router.get("/health/summary")
async def get_system_health_summary(
    settings: Settings = Depends(get_settings),
    _auth: Dict[str, Any] = Depends(verify_client_auth_details),
) -> Dict[str, Any]:
    """Comprehensive readiness probe across Gateway, SQLite, Redis, Ollama, and Classifier."""
    # 1. SQLite
    db_healthy = False
    try:
        engine = get_engine(settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_healthy = True
    except Exception:
        pass

    # 2. Redis
    redis_healthy = False
    try:
        from app.cache import get_cache
        c = await get_cache(settings)._get_client()
        if c and (await c.ping()):
            redis_healthy = True
    except Exception:
        pass

    # 3. Ollama
    ollama_healthy = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            if resp.status_code == 200:
                ollama_healthy = True
    except Exception:
        pass

    # 4. Overall status
    overall = "healthy"
    if not db_healthy:
        overall = "degraded"
    if settings.cache_enabled and not redis_healthy and settings.cache_failure_policy == "fail_closed":
        overall = "unavailable"

    return {
        "status": overall,
        "gateway": "healthy",
        "database": "healthy" if db_healthy else "unavailable",
        "redis": "healthy" if redis_healthy else ("disabled" if not settings.cache_enabled else "unavailable"),
        "ollama": "healthy" if ollama_healthy else "offline",
        "app_env": settings.app_env,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------------------
# Sanitized Gateway Configuration
# ------------------------------------------------------------------------------

@management_router.get("/config")
async def get_sanitized_config(
    settings: Settings = Depends(get_settings),
    _admin: Dict[str, Any] = Depends(verify_admin_access),
) -> Dict[str, Any]:
    """Expose safe, non-sensitive gateway operational configuration."""
    return {
        "app_env": settings.app_env,
        "log_level": settings.log_level,
        "active_provider": settings.active_provider,
        "ollama_base_url": settings.ollama_base_url,
        "allowed_models": settings.allowed_models,
        "max_request_size_bytes": settings.max_request_size_bytes,
        "provider_timeout_seconds": settings.provider_timeout_seconds,
        "cache": {
            "enabled": settings.cache_enabled,
            "ttl_seconds": settings.cache_ttl_seconds,
            "namespace": settings.cache_namespace,
            "failure_policy": settings.cache_failure_policy,
            "semantic_cache_enabled": getattr(settings, "semantic_cache_enabled", False),
            "semantic_cache_threshold": getattr(settings, "semantic_cache_threshold", 0.85),
        },
        "rate_limiting": {
            "enabled": settings.rate_limit_enabled,
            "requests": settings.rate_limit_requests,
            "window_seconds": settings.rate_limit_window_seconds,
            "failure_policy": settings.rate_limit_failure_policy,
        },
        "guardrails": {
            "enabled": settings.guardrails_enabled,
            "input_enabled": settings.guardrails_input_enabled,
            "output_enabled": settings.guardrails_output_enabled,
            "max_text_length": settings.guardrails_max_text_length,
            "rules_count": len(settings.guardrails_rules),
        },
        "failover": {
            "enabled": settings.failover_enabled,
            "max_attempts": settings.failover_max_attempts,
            "timeout_budget_seconds": settings.failover_timeout_budget_seconds,
        },
        "metrics": {
            "enabled": settings.metrics_enabled,
            "path": settings.metrics_path,
            "require_auth": settings.metrics_require_auth,
        },
    }
