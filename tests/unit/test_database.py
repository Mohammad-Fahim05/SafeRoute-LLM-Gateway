"""Unit tests for SQLite database layer, schema constraints, foreign keys, and persistence."""

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Client, RequestRecord, UsageRecord
from app.db.service import DatabaseService
from app.db.session import configure_sqlite_connection


@pytest.fixture
def standalone_sqlite(tmp_path):
    """Create isolated SQLite database with foreign keys and WAL mode enabled."""
    db_file = tmp_path / "standalone.db"
    engine = create_engine(f"sqlite:///{db_file}")
    from sqlalchemy import event
    event.listen(engine, "connect", configure_sqlite_connection)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


def test_database_initialization_and_schema(standalone_sqlite):
    """Requirement 1 & 2: Verify table initialization and expected table schemas."""
    inspector = inspect(standalone_sqlite)
    tables = inspector.get_table_names()

    assert "clients" in tables
    assert "api_key_audits" in tables
    assert "request_records" in tables
    assert "usage_records" in tables

    # Verify column existence in request_records
    req_columns = {col["name"] for col in inspector.get_columns("request_records")}
    assert "request_id" in req_columns
    assert "client_id" in req_columns
    assert "http_status" in req_columns
    assert "duration_ms" in req_columns
    assert "provider_latency_ms" in req_columns


def test_request_record_persistence_across_sessions(standalone_sqlite):
    """Requirement 3 & 4: Create record in session 1, verify readable in independent session 2."""
    service = DatabaseService(engine=standalone_sqlite)

    # Session 1: Create request record
    req = service.record_request_outcome(
        request_id="req_persist_12345",
        client_id="client_session_test",
        model_requested="mock-model",
        provider="mock",
        http_status=200,
        status="success",
        duration_ms=12.5,
        provider_latency_ms=8.2,
        input_tokens=20,
        output_tokens=30,
        total_tokens=50,
        usage_source="mock_estimated",
        is_estimate=True,
    )
    assert req.id is not None

    # Session 2: Read record using a completely fresh session
    SessionLocal = sessionmaker(bind=standalone_sqlite)
    with SessionLocal() as session:
        fetched = session.scalar(
            select(RequestRecord).where(RequestRecord.request_id == "req_persist_12345")
        )
        assert fetched is not None
        assert fetched.client_id == "client_session_test"
        assert fetched.http_status == 200
        assert fetched.status == "success"
        assert fetched.duration_ms == 12.5
        assert fetched.provider_latency_ms == 8.2

        # Verify joined usage record
        assert fetched.usage is not None
        assert fetched.usage.input_tokens == 20
        assert fetched.usage.output_tokens == 30
        assert fetched.usage.total_tokens == 50
        assert fetched.usage.is_estimate is True
        assert fetched.usage.calculation_status == "mock_excluded"


def test_request_id_uniqueness_enforced(standalone_sqlite):
    """Requirement 5: Duplicate request_id raises IntegrityError."""
    service = DatabaseService(engine=standalone_sqlite)

    # First write succeeds
    service.record_request_outcome(
        request_id="req_unique_conflict",
        client_id="client_a",
        model_requested="mock-model",
        provider="mock",
        http_status=200,
        status="success",
        duration_ms=10.0,
    )

    # Second write with same request_id must fail uniqueness constraint
    with pytest.raises(IntegrityError):
        service.record_request_outcome(
            request_id="req_unique_conflict",
            client_id="client_b",
            model_requested="mock-model",
            provider="mock",
            http_status=200,
            status="success",
            duration_ms=10.0,
        )


def test_foreign_key_enforcement_and_cascade_delete(standalone_sqlite):
    """Requirement 6: Verify foreign key enforcement and cascade delete."""
    SessionLocal = sessionmaker(bind=standalone_sqlite)

    # 1. Reject invalid foreign key referencing non-existent request record
    with SessionLocal() as session:
        orphan_usage = UsageRecord(
            request_record_id=999999,  # Non-existent
            usage_source="unavailable",
            provider="mock",
            model="mock-model",
            currency="USD",
            calculation_status="mock_excluded",
        )
        session.add(orphan_usage)
        with pytest.raises(IntegrityError):
            session.commit()

    # 2. Verify cascade delete
    service = DatabaseService(engine=standalone_sqlite)
    record = service.record_request_outcome(
        request_id="req_to_delete",
        client_id="client_del",
        model_requested="mock-model",
        provider="mock",
        http_status=200,
        status="success",
        duration_ms=5.0,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
    )
    req_id = record.id

    with SessionLocal() as session:
        to_delete = session.get(RequestRecord, req_id)
        assert to_delete is not None
        session.delete(to_delete)
        session.commit()

        # Both request record and usage record should be deleted
        assert session.get(RequestRecord, req_id) is None
        assert session.scalar(select(UsageRecord).where(UsageRecord.request_record_id == req_id)) is None
