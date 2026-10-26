"""Database service layer for recording requests, aggregating metrics, and exporting CSV."""

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import Engine, func, select

from app.core.logging import logger
from app.db.models import Client, RequestRecord, UsageRecord
from app.db.session import get_db_session
from app.pricing.calculator import pricing_engine


class DatabaseService:
    """Encapsulates business operations for database persistence and querying."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self.engine = engine

    def sync_client(self, client_id: str, description: Optional[str] = None) -> None:
        """Ensure client record exists in database."""
        if not client_id or client_id in ("anonymous", "anonymous_dev"):
            return

        with get_db_session(self.engine) as session:
            stmt = select(Client).where(Client.client_id == client_id)
            existing = session.scalar(stmt)
            if not existing:
                client = Client(
                    client_id=client_id,
                    created_at=datetime.now(timezone.utc),
                    is_active=True,
                    description=description or f"Registered client {client_id}",
                )
                session.add(client)

    def record_request_outcome(
        self,
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
    ) -> RequestRecord:
        """Persist request outcome and associated usage record with cost calculation."""
        # 1. Sync client if valid identifier present
        if client_id and client_id not in ("anonymous", "anonymous_dev"):
            try:
                self.sync_client(client_id)
            except Exception as exc:
                logger.debug(f"Client sync note: {exc}")

        actual_model = model_actual or model_requested

        # 2. Calculate cost based on versioned pricing or cache hit
        if cache_status in ("hit", "exact_hit", "semantic_hit"):
            # Cache hits do not incur upstream provider costs
            pricing_version: Optional[str] = None
            input_cost: Optional[Decimal] = Decimal("0.000000")
            output_cost: Optional[Decimal] = Decimal("0.000000")
            total_cost: Optional[Decimal] = Decimal("0.000000")
            calculation_status: str = "cache_hit"
            currency: str = "USD"
        else:
            pricing_res = pricing_engine.calculate_cost(
                model=actual_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                provider=provider,
            )
            pricing_version = pricing_res.pricing_version
            input_cost = pricing_res.input_cost
            output_cost = pricing_res.output_cost
            total_cost = pricing_res.total_cost
            calculation_status = pricing_res.calculation_status
            currency = pricing_res.currency

        with get_db_session(self.engine) as session:
            # 3. Create RequestRecord
            req_record = RequestRecord(
                request_id=request_id,
                client_id=client_id,
                created_at=datetime.now(timezone.utc),
                model_requested=model_requested,
                model_actual=actual_model,
                provider=provider,
                http_status=http_status,
                status=status,
                error_code=error_code,
                error_message=error_message,
                duration_ms=duration_ms,
                provider_latency_ms=provider_latency_ms,
                cache_status=cache_status,
                token_usage_status=usage_source,
                attempts_count=attempts_count,
                failover_occurred=failover_occurred,
                attempt_sequence=attempt_sequence,
                stream=stream,
                stream_status=stream_status,
            )
            session.add(req_record)
            session.flush()  # Obtain req_record.id

            # 4. Create UsageRecord
            usage_record = UsageRecord(
                request_record_id=req_record.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                usage_source=usage_source,
                is_estimate=is_estimate,
                provider=provider,
                model=actual_model,
                pricing_version=pricing_version,
                input_cost=input_cost,
                output_cost=output_cost,
                total_cost=total_cost,
                currency=currency,
                calculation_status=calculation_status,
            )
            session.add(usage_record)

            session.commit()
            session.refresh(req_record)
            return req_record

    def get_usage_summary(
        self,
        client_id: str,
    ) -> Dict[str, Any]:
        """Query aggregated usage statistics strictly scoped to the authenticated client."""
        with get_db_session(self.engine) as session:
            # Base query filtered by client_id
            req_stmt = select(RequestRecord).where(RequestRecord.client_id == client_id)
            requests = session.scalars(req_stmt).all()

            total_requests = len(requests)
            successful_requests = sum(1 for r in requests if r.status == "success")
            failed_requests = sum(1 for r in requests if r.status == "failed")
            cache_hits = sum(1 for r in requests if r.cache_status in ("hit", "exact_hit", "semantic_hit"))
            cache_misses = sum(1 for r in requests if r.cache_status in ("miss", "exact_miss", "semantic_miss"))

            # Provider breakdown (cache hits do not count as new upstream calls)
            provider_counts: Dict[str, int] = {}
            for r in requests:
                if r.cache_status not in ("hit", "exact_hit", "semantic_hit"):
                    provider_counts[r.provider] = provider_counts.get(r.provider, 0) + 1

            # Latency averages
            gateway_latencies = [r.duration_ms for r in requests if r.duration_ms is not None]
            avg_gateway_latency = (
                round(sum(gateway_latencies) / len(gateway_latencies), 2)
                if gateway_latencies
                else 0.0
            )

            provider_latencies = [
                r.provider_latency_ms for r in requests if r.provider_latency_ms is not None
            ]
            avg_provider_latency = (
                round(sum(provider_latencies) / len(provider_latencies), 2)
                if provider_latencies
                else 0.0
            )

            # Token and cost aggregations from joined usage records
            usage_stmt = (
                select(UsageRecord)
                .join(RequestRecord)
                .where(RequestRecord.client_id == client_id)
            )
            usages = session.scalars(usage_stmt).all()

            known_in_tokens = 0
            known_out_tokens = 0
            known_tot_tokens = 0
            unavailable_usage_count = 0
            mock_requests_count = 0
            unknown_cost_count = 0
            estimated_cloud_cost = Decimal("0.0")

            for u in usages:
                if u.usage_source == "mock_estimated":
                    mock_requests_count += 1
                elif u.usage_source == "unavailable":
                    unavailable_usage_count += 1
                elif u.usage_source in ("cache_hit", "semantic_cache_hit"):
                    # Cache hit does not consume new provider tokens
                    continue

                if u.input_tokens is not None:
                    known_in_tokens += u.input_tokens
                if u.output_tokens is not None:
                    known_out_tokens += u.output_tokens
                if u.total_tokens is not None:
                    known_tot_tokens += u.total_tokens

                if u.calculation_status == "calculated" and u.total_cost is not None:
                    estimated_cloud_cost += u.total_cost
                elif u.calculation_status == "unknown_model":
                    unknown_cost_count += 1

            return {
                "client_id": client_id,
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "failed_requests": failed_requests,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "provider_counts": provider_counts,
                "known_input_tokens": known_in_tokens,
                "known_output_tokens": known_out_tokens,
                "known_total_tokens": known_tot_tokens,
                "unavailable_usage_count": unavailable_usage_count,
                "mock_requests_count": mock_requests_count,
                "estimated_cloud_cost": float(estimated_cloud_cost),
                "unknown_cost_count": unknown_cost_count,
                "currency": "USD",
                "avg_gateway_latency_ms": avg_gateway_latency,
                "avg_provider_latency_ms": avg_provider_latency,
            }

    def export_records_csv(self, client_id: Optional[str] = None) -> str:
        """Export authorized request and usage records to CSV format."""
        with get_db_session(self.engine) as session:
            stmt = select(RequestRecord).order_by(RequestRecord.created_at.asc())
            if client_id:
                stmt = stmt.where(RequestRecord.client_id == client_id)

            records = session.scalars(stmt).all()

            output = io.StringIO()
            writer = csv.writer(output)

            # CSV Headers (strictly excluding raw prompts and secrets)
            writer.writerow([
                "request_id",
                "timestamp_utc",
                "client_id",
                "provider",
                "model_requested",
                "model_actual",
                "http_status",
                "status",
                "cache_status",
                "error_code",
                "duration_ms",
                "provider_latency_ms",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "usage_source",
                "pricing_version",
                "total_cost",
                "currency",
                "calculation_status",
                "attempts_count",
                "failover_occurred",
            ])

            for r in records:
                u = r.usage
                writer.writerow([
                    r.request_id,
                    r.created_at.isoformat() if r.created_at else "",
                    r.client_id or "",
                    r.provider,
                    r.model_requested,
                    r.model_actual or "",
                    r.http_status,
                    r.status,
                    r.cache_status or "not_applicable",
                    r.error_code or "",
                    r.duration_ms,
                    r.provider_latency_ms if r.provider_latency_ms is not None else "",
                    u.input_tokens if u and u.input_tokens is not None else "",
                    u.output_tokens if u and u.output_tokens is not None else "",
                    u.total_tokens if u and u.total_tokens is not None else "",
                    u.usage_source if u else "",
                    u.pricing_version if u and u.pricing_version else "",
                    str(u.total_cost) if u and u.total_cost is not None else "",
                    u.currency if u else "USD",
                    u.calculation_status if u else "",
                    r.attempts_count if hasattr(r, "attempts_count") else 1,
                    r.failover_occurred if hasattr(r, "failover_occurred") else False,
                ])

            return output.getvalue()


db_service = DatabaseService()
