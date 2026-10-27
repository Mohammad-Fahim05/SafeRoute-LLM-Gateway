"""Production readiness and operational resilience tests for SafeRoute LLM Gateway."""

import asyncio
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from app.api.schemas import ChatCompletionRequest, ChatMessage
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.main import create_app, lifespan

TEST_SECRET = "production_readiness_secret_16_chars_min"
CLIENT_KEY = "gw_prod_client_key_1234567890123456"
CLIENT_VERIFIER = compute_key_verifier(CLIENT_KEY, TEST_SECRET)


def build_prod_setup(
    test_db_url: str,
    strict_db: bool = False,
    cache_policy: str = "fail_open",
):
    """Initialize test environment for production readiness verification."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        database_strict_mode=strict_db,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "prod_tester", "verifier": CLIENT_VERIFIER, "enabled": True}],
        allowed_models=["mock-model"],
        default_model="mock-model",
        active_provider="mock",
        cache_enabled=False,
        rate_limit_enabled=False,
        safety_classifier_enabled=True,
        safety_classifier_provider="mock",
    )
    engine = get_engine(settings.database_url)
    init_db(engine)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return app, settings


def test_health_probe_returns_200(test_db_url: str):
    """Verify /health liveness probe returns HTTP 200 with service operational status."""
    app, settings = build_prod_setup(test_db_url)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["app"] == "SafeRoute LLM Gateway"
        assert "environment" in data


def test_readiness_probe_returns_200_when_healthy(test_db_url: str):
    """Verify /ready probe returns HTTP 200 with database, redis, safety model, and provider status."""
    app, settings = build_prod_setup(test_db_url)
    with TestClient(app) as client:
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["database"] == "available"
        assert "providers" in data
        assert "redis" in data
        assert "safety_classifier" in data


def test_readiness_probe_returns_503_when_database_fails_in_strict_mode(test_db_url: str):
    """Verify /ready probe marks gateway not_ready (HTTP 503) if database is unavailable in strict mode."""
    app, settings = build_prod_setup(test_db_url, strict_db=True)
    with TestClient(app) as client:
        # Simulate broken database connection
        with patch("app.db.session.get_engine") as mock_engine:
            mock_engine.side_effect = RuntimeError("Database socket connection lost")
            resp = client.get("/ready")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "not_ready"
            assert data["database"] == "unavailable"


@pytest.mark.anyio
async def test_lifespan_prewarms_safety_model_at_startup(test_db_url: str):
    """Verify application lifespan startup event pre-warms local safety classifier to eliminate cold start."""
    pytest.importorskip("sentence_transformers")
    test_settings = Settings(
        app_env="test",
        database_url=test_db_url,
        safety_classifier_enabled=True,
        safety_classifier_provider="local",
    )
    app = create_app(test_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings


    # Track whether _ensure_loaded was invoked during lifespan startup
    prewarmed = False
    from app.guardrails.classifier import LocalSemanticSafetyClassifier

    orig_ensure = LocalSemanticSafetyClassifier._ensure_loaded

    async def mock_ensure(self):
        nonlocal prewarmed
        prewarmed = True
        return await orig_ensure(self)

    with patch.object(LocalSemanticSafetyClassifier, "_ensure_loaded", mock_ensure):
        async with lifespan(app):
            assert prewarmed is True


def test_secrets_never_exposed_in_error_payloads(test_db_url: str):
    """Verify client secrets, auth tokens, and internal keys are never exposed in error responses."""
    app, settings = build_prod_setup(test_db_url)
    with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
        # Send an invalid request triggering schema validation error
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "temperature": -5.0},
        )
        assert resp.status_code == 422
        body_text = resp.text
        # Assert none of the sensitive tokens exist anywhere in the response body
        assert TEST_SECRET not in body_text
        assert CLIENT_KEY not in body_text
        assert CLIENT_VERIFIER not in body_text


def test_concurrent_requests_handled_safely(test_db_url: str):
    """Verify concurrent requests are executed safely without race conditions or thread deadlocks."""
    app, settings = build_prod_setup(test_db_url)

    def send_one(req_num: int):
        with TestClient(app, headers={"Authorization": f"Bearer {CLIENT_KEY}"}) as client:
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock-model",
                    "messages": [{"role": "user", "content": f"Concurrent test request #{req_num}"}],
                },
            )
            return resp.status_code, resp.headers.get("X-Request-ID")

    import concurrent.futures

    # Run 10 parallel requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(send_one, i) for i in range(10)]
        results = [f.result() for f in futures]

    statuses = [r[0] for r in results]
    request_ids = [r[1] for r in results]

    assert all(s == 200 for s in statuses)
    # Ensure every concurrent request received a unique Request ID
    assert len(set(request_ids)) == 10


def test_readiness_probe_rate_limit_fail_closed_redis_unavailable(test_db_url: str):
    """Verify /ready probe returns HTTP 503 when rate limiting is enabled and fail_closed with Redis down."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        database_strict_mode=False,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "prod_tester", "verifier": CLIENT_VERIFIER, "enabled": True}],
        allowed_models=["mock-model"],
        default_model="mock-model",
        active_provider="mock",
        cache_enabled=False,
        rate_limit_enabled=True,
        rate_limit_failure_policy="fail_closed",
        safety_classifier_enabled=False,
    )
    engine = get_engine(settings.database_url)
    init_db(engine)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        # Mock Redis client as unreachable
        with patch("app.limiter.redis_limiter.RateLimiter._get_client") as mock_get_client:
            mock_get_client.side_effect = RuntimeError("Redis connection refused")
            resp = client.get("/ready")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "not_ready"
            assert data["redis"] == "unavailable"


def test_readiness_probe_rate_limit_fail_open_redis_unavailable(test_db_url: str):
    """Verify /ready probe returns HTTP 200 when rate limiting is fail_open despite Redis being down."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        database_strict_mode=False,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "prod_tester", "verifier": CLIENT_VERIFIER, "enabled": True}],
        allowed_models=["mock-model"],
        default_model="mock-model",
        active_provider="mock",
        cache_enabled=False,
        rate_limit_enabled=True,
        rate_limit_failure_policy="fail_open",
        safety_classifier_enabled=False,
    )
    engine = get_engine(settings.database_url)
    init_db(engine)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        with patch("app.limiter.redis_limiter.RateLimiter._get_client") as mock_get_client:
            mock_get_client.side_effect = RuntimeError("Redis connection refused")
            resp = client.get("/ready")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ready"
            assert data["redis"] == "unavailable"


def test_sqlite_connection_settings_applied(test_db_url: str):
    """Verify SQLite connection event listener enforces PRAGMA busy_timeout, foreign_keys, and WAL mode."""
    reset_db_engine()
    from sqlalchemy import text
    engine = get_engine(test_db_url)
    with engine.connect() as conn:
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()

        assert busy_timeout == 15000
        assert foreign_keys == 1
        assert str(journal_mode).lower() == "wal"


def test_sqlite_concurrent_writes_and_persistence_integrity(test_db_url: str):
    """Verify concurrent thread writes to SQLite complete without lock failures and maintain database integrity."""
    reset_db_engine()
    from app.db.service import DatabaseService
    import concurrent.futures
    import sqlite3

    engine = get_engine(test_db_url)
    init_db(engine)
    db_svc = DatabaseService(engine=engine)

    num_concurrent_writers = 20

    def write_worker(idx: int):
        req_id = f"req_concurrent_stress_{idx}_{time.time()}"
        res = db_svc.record_request_outcome(
            request_id=req_id,
            client_id="prod_tester",
            model_requested="mock-model",
            model_actual="mock-model",
            provider="mock",
            http_status=200,
            status="success",
            duration_ms=12.5,
            provider_latency_ms=10.0,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            usage_source="provider",
            is_estimate=False,
            cache_status="miss",
        )
        return res

    import time
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_worker, i) for i in range(num_concurrent_writers)]
        results = [f.result() for f in futures]

    assert len(results) == num_concurrent_writers
    assert all(r is not None for r in results)

    # Verify actual database records written and foreign key integrity
    db_path = test_db_url.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM request_records WHERE request_id LIKE 'req_concurrent_stress_%'")
    req_count = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM usage_records u JOIN request_records r ON u.request_record_id = r.id WHERE r.client_id = 'prod_tester'"
    )
    usage_count = cur.fetchone()[0]
    conn.close()

    assert req_count == num_concurrent_writers
    assert usage_count == num_concurrent_writers


def test_docker_compose_configuration_mapping():
    """Verify docker-compose.yml maps streaming, replay, and metrics variables with correct defaults."""
    from pathlib import Path
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists()
    content = compose_path.read_text(encoding="utf-8")

    assert "STREAMING_ENABLED=${STREAMING_ENABLED:-true}" in content
    assert "STREAMING_CACHE_REPLAY_ENABLED=${STREAMING_CACHE_REPLAY_ENABLED:-true}" in content
    assert "METRICS_ENABLED=${METRICS_ENABLED:-true}" in content
    assert "METRICS_REQUIRE_AUTH=${METRICS_REQUIRE_AUTH:-false}" in content


def test_cors_preflight_and_restricted_origins(test_db_url: str):
    """Verify CORS preflight OPTIONS and origin filtering enforcement."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        cors_allowed_origins=["https://allowed-portal.example.com"],
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "prod_tester", "verifier": CLIENT_VERIFIER, "enabled": True}],
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        # Preflight from authorized origin
        preflight_resp = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://allowed-portal.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight_resp.status_code == 200
        assert preflight_resp.headers.get("access-control-allow-origin") == "https://allowed-portal.example.com"
        assert "POST" in preflight_resp.headers.get("access-control-allow-methods", "")

        # Request from disallowed origin must not receive allow-origin header
        unauthorized_resp = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "https://malicious-site.attacker.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in unauthorized_resp.headers


def test_defensive_http_security_headers(test_db_url: str):
    """Verify X-Content-Type-Options: nosniff and X-Frame-Options: DENY on normal and error responses."""
    reset_db_engine()
    from app.core.auth import compute_key_verifier

    key = "gw_test_key_11111111111111111111"
    verifier = compute_key_verifier(key, TEST_SECRET)

    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[{"client_id": "prod_tester", "verifier": verifier, "enabled": True}],
        max_request_size_bytes=100,
    )
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        # 1. Successful public endpoint
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.headers.get("x-content-type-options") == "nosniff"
        assert r_health.headers.get("x-frame-options") == "DENY"

        # 2. Authentication failure (HTTP 401)
        r_auth_fail = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r_auth_fail.status_code == 401
        assert r_auth_fail.headers.get("x-content-type-options") == "nosniff"
        assert r_auth_fail.headers.get("x-frame-options") == "DENY"

        # 3. Payload too large (HTTP 413)
        r_large = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Length": "5000",
            },
            content="x" * 5000,
        )
        assert r_large.status_code == 413
        assert r_large.headers.get("x-content-type-options") == "nosniff"
        assert r_large.headers.get("x-frame-options") == "DENY"


def test_strict_client_isolation_and_cross_tenant_confidentiality(test_db_url: str):
    """Verify strict tenant isolation: client B cannot view client A records or usage statistics."""
    reset_db_engine()
    from app.core.auth import compute_key_verifier
    from app.db.service import DatabaseService

    key_alice = "gw_alice_key_11111111111111111111"
    key_bob = "gw_bob_key_2222222222222222222222"
    ver_alice = compute_key_verifier(key_alice, TEST_SECRET)
    ver_bob = compute_key_verifier(key_bob, TEST_SECRET)

    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        auth_enabled=True,
        auth_secret=TEST_SECRET,
        client_keys=[
            {"client_id": "alice", "verifier": ver_alice, "enabled": True},
            {"client_id": "bob", "verifier": ver_bob, "enabled": True},
        ],
        allowed_models=["mock-model"],
        default_model="mock-model",
        active_provider="mock",
    )
    engine = get_engine(settings.database_url)
    init_db(engine)

    # Alice generates activity
    db_svc = DatabaseService(engine=engine)
    db_svc.record_request_outcome(
        request_id="req_alice_secret_1",
        client_id="alice",
        model_requested="mock-model",
        model_actual="mock-model",
        provider="mock",
        http_status=200,
        status="success",
        duration_ms=12.0,
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
    )

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        # Bob checks summary - must see 0 usage and 0 records
        r_bob_summary = client.get(
            "/v1/usage/summary",
            headers={"Authorization": f"Bearer {key_bob}"},
        )
        assert r_bob_summary.status_code == 200
        bob_data = r_bob_summary.json()
        assert bob_data["client_id"] == "bob"
        assert bob_data["total_requests"] == 0
        assert bob_data["known_total_tokens"] == 0

        # Bob checks CSV export - must be empty data rows
        r_bob_export = client.get(
            "/v1/usage/export",
            headers={"Authorization": f"Bearer {key_bob}"},
        )
        assert r_bob_export.status_code == 200
        csv_lines = [line.strip() for line in r_bob_export.text.strip().split("\n") if line.strip()]
        # Only header row
        assert len(csv_lines) == 1
        assert "req_alice_secret_1" not in r_bob_export.text
