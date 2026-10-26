"""SQLAlchemy declarative models for clients, requests, and usage records."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy database models."""
    pass


class Client(Base):
    """Registered API clients."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    api_keys: Mapped[list["ApiKeyAudit"]] = relationship(
        "ApiKeyAudit", back_populates="client", cascade="all, delete-orphan"
    )


class ApiKeyAudit(Base):
    """Audit log of registered client API key verifiers (never stores plaintext keys)."""

    __tablename__ = "api_key_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("clients.client_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_verifier: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    client: Mapped["Client"] = relationship("Client", back_populates="api_keys")


class RequestRecord(Base):
    """Durable record of incoming chat completion requests."""

    __tablename__ = "request_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    model_requested: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    model_actual: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)  # "success" or "failed"
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    provider_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cache_status: Mapped[str] = mapped_column(String(32), default="not_applicable", nullable=False)
    token_usage_status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    failover_occurred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    attempt_sequence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stream: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    stream_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    usage: Mapped[Optional["UsageRecord"]] = relationship(
        "UsageRecord", back_populates="request", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_request_records_client_created", "client_id", "created_at"),
        Index("ix_request_records_provider_status", "provider", "status"),
    )


class UsageRecord(Base):
    """Detailed token usage and calculated cost breakdown linked to a request."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("request_records.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usage_source: Mapped[str] = mapped_column(String(32), nullable=False)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    pricing_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    input_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    output_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    total_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(32), nullable=False)

    request: Mapped["RequestRecord"] = relationship("RequestRecord", back_populates="usage")
