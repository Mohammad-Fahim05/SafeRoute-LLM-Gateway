"""SQLAlchemy database engine, session management, and SQLite optimizations."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker[Session]] = None


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    """Enforce SQLite foreign keys, busy timeout, and WAL mode for reliability and performance."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()


def ensure_db_dir_exists(database_url: str) -> None:
    """Ensure directory exists if using a local file-based SQLite database."""
    if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite:///:memory:"):
        path_str = database_url.replace("sqlite:///", "")
        db_path = Path(path_str).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(database_url: Optional[str] = None) -> Engine:
    """Get or create singleton SQLAlchemy Engine."""
    global _engine
    if database_url is not None:
        if _engine is None or str(_engine.url) != database_url:
            ensure_db_dir_exists(database_url)
            connect_args = (
                {"check_same_thread": False, "timeout": 15.0}
                if database_url.startswith("sqlite")
                else {}
            )
            _engine = create_engine(database_url, connect_args=connect_args)
        return _engine

    if _engine is None:
        url = get_settings().database_url
        ensure_db_dir_exists(url)
        connect_args = (
            {"check_same_thread": False, "timeout": 15.0}
            if url.startswith("sqlite")
            else {}
        )
        _engine = create_engine(url, connect_args=connect_args)

    return _engine



def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Get or create Session factory."""
    global _SessionFactory
    eng = engine or get_engine()
    if _SessionFactory is None or _SessionFactory.kw.get("bind") != eng:
        _SessionFactory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    return _SessionFactory


@contextmanager
def get_db_session(engine: Optional[Engine] = None) -> Generator[Session, None, None]:
    """Context manager providing a transactional database session."""
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Optional[Engine] = None) -> None:
    """Create all declared database tables if they do not exist, and migrate columns."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)

    # Backward-compatible column check for SQLite
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(eng)
        if "request_records" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("request_records")]
            with eng.connect() as conn:
                if "attempts_count" not in columns:
                    conn.execute(text("ALTER TABLE request_records ADD COLUMN attempts_count INTEGER NOT NULL DEFAULT 1"))
                if "failover_occurred" not in columns:
                    conn.execute(text("ALTER TABLE request_records ADD COLUMN failover_occurred BOOLEAN NOT NULL DEFAULT 0"))
                if "attempt_sequence" not in columns:
                    conn.execute(text("ALTER TABLE request_records ADD COLUMN attempt_sequence TEXT"))
                if "stream" not in columns:
                    conn.execute(text("ALTER TABLE request_records ADD COLUMN stream BOOLEAN NOT NULL DEFAULT 0"))
                if "stream_status" not in columns:
                    conn.execute(text("ALTER TABLE request_records ADD COLUMN stream_status TEXT"))
                conn.commit()
    except Exception:
        pass


def reset_db_engine() -> None:
    """Reset cached engine and session factory (useful for tests)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _SessionFactory = None
