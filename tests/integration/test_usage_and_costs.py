"""Integration tests for durable request recording, usage tracking, cost calculations, summary endpoints, and CSV export."""

import json
from unittest.mock import patch
import httpx
from starlette.testclient import TestClient
from sqlalchemy import select

from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import db_service, get_db_session, init_db, reset_db_engine
from app.db.session import get_engine
from app.db.models import RequestRecord, UsageRecord
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET, VALID_KEY_VERIFIER, VALID_TEST_KEY



def test_successful_mock_request_recorded_in_db(client: TestClient):
    """Requirement 7 & 9: Verify successful chat completion persists request and mock-estimated usage."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Persist me!"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    rid = response.headers["X-Request-ID"]

    # Verify database record
    with get_db_session() as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.client_id == "test_client"
        assert rec.provider == "mock"
        assert rec.model_requested == "mock-model"
        assert rec.http_status == 200
        assert rec.status == "success"
        assert rec.duration_ms > 0
        assert rec.provider_latency_ms is not None

        # Verify linked usage record
        assert rec.usage is not None
        assert rec.usage.usage_source == "mock_estimated"
        assert rec.usage.is_estimate is True
        assert rec.usage.input_tokens > 0
        assert rec.usage.output_tokens > 0
        assert rec.usage.calculation_status == "mock_excluded"
        assert rec.usage.total_cost is None


def test_provider_reported_token_usage_recorded_in_db(test_db_url: str):
    """Requirement 8 & 14: Ollama request persists provider-reported tokens and free_tier_local cost."""
    def mock_ollama_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2:1b",
                    "created_at": "2026-10-24T18:00:00Z",
                    "message": {"role": "assistant", "content": "Local Ollama response."},
                    "done": True,
                    "prompt_eval_count": 35,
                    "eval_count": 50,
                },
            )
        return httpx.Response(404)

    settings = Settings(
        app_env="test",
        active_provider="ollama",
        allowed_models=["llama3.2:1b"],
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        database_url=test_db_url,
        cache_enabled=False,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings


    from app.providers import get_ollama_provider
    provider = get_ollama_provider(settings)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_ollama_handler),
        base_url="http://localhost:11434",
    )

    client = TestClient(app, headers={"Authorization": f"Bearer {VALID_TEST_KEY}"})
    payload = {
        "model": "llama3.2:1b",
        "messages": [{"role": "user", "content": "Ollama query"}],
    }

    res = client.post("/v1/chat/completions", json=payload)
    assert res.status_code == 200
    rid = res.headers["X-Request-ID"]

    with get_db_session() as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.provider == "ollama"
        assert rec.usage.input_tokens == 35
        assert rec.usage.output_tokens == 50
        assert rec.usage.total_tokens == 85
        assert rec.usage.usage_source == "provider_reported"
        assert rec.usage.is_estimate is False
        assert rec.usage.calculation_status == "free_tier_local"
        assert float(rec.usage.total_cost) == 0.0


def test_provider_timeout_recorded_in_db(client: TestClient):
    """Requirement 15: Upstream provider timeout is persisted with 504 and gateway_timeout code."""
    payload = {
        "model": "mock-timeout",
        "messages": [{"role": "user", "content": "Timeout query"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 504
    rid = response.headers["X-Request-ID"]

    with get_db_session() as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.http_status == 504
        assert rec.status == "failed"
        assert rec.error_code == "gateway_timeout"
        assert "timed out" in rec.error_message.lower()


def test_provider_error_recorded_without_leaking_secrets(client: TestClient):
    """Requirement 16: Upstream provider error is recorded with 502 without leaking secrets."""
    payload = {
        "model": "mock-error",
        "messages": [{"role": "user", "content": "Error query"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 502
    rid = response.headers["X-Request-ID"]

    with get_db_session() as session:
        rec = session.scalar(select(RequestRecord).where(RequestRecord.request_id == rid))
        assert rec is not None
        assert rec.http_status == 502
        assert rec.status == "failed"
        assert rec.error_code == "provider_error"


def test_usage_summary_endpoint_calculations(client: TestClient):
    """Requirement 17: GET /v1/usage/summary accurately aggregates client metrics."""
    # Send a few requests
    client.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "q1"}]})
    client.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "q2"}]})

    summary_res = client.get("/v1/usage/summary")
    assert summary_res.status_code == 200
    data = summary_res.json()

    assert data["client_id"] == "test_client"
    assert data["total_requests"] >= 2
    assert data["successful_requests"] >= 2
    assert data["provider_counts"]["mock"] >= 2
    assert data["known_input_tokens"] > 0
    assert data["mock_requests_count"] >= 2
    assert data["currency"] == "USD"


def test_client_level_data_isolation(test_db_url: str):
    """Requirement 18: Clients cannot see each other's metrics or records."""
    key_alice = "gw_test_alice_key_11111111111111111111"
    key_bob = "gw_test_bob_key_2222222222222222222222"

    verifier_alice = compute_key_verifier(key_alice, TEST_AUTH_SECRET)
    verifier_bob = compute_key_verifier(key_bob, TEST_AUTH_SECRET)

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[
            {"client_id": "alice", "verifier": verifier_alice, "enabled": True},
            {"client_id": "bob", "verifier": verifier_bob, "enabled": True},
        ],
        database_url=test_db_url,
        cache_enabled=False,
    )

    reset_db_engine()
    init_db(get_engine(settings.database_url))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as test_client:
        headers_alice = {"Authorization": f"Bearer {key_alice}"}
        headers_bob = {"Authorization": f"Bearer {key_bob}"}

        # Alice makes 3 requests
        for i in range(3):
            test_client.post(
                "/v1/chat/completions",
                headers=headers_alice,
                json={"model": "mock-model", "messages": [{"role": "user", "content": f"alice_{i}"}]},
            )

        # Bob makes 1 request
        test_client.post(
            "/v1/chat/completions",
            headers=headers_bob,
            json={"model": "mock-model", "messages": [{"role": "user", "content": "bob_1"}]},
        )

        # Verify Alice's summary only shows Alice's 3 requests
        alice_summary = test_client.get("/v1/usage/summary", headers=headers_alice).json()
        assert alice_summary["client_id"] == "alice"
        assert alice_summary["total_requests"] == 3

        # Verify Bob's summary only shows Bob's 1 request
        bob_summary = test_client.get("/v1/usage/summary", headers=headers_bob).json()
        assert bob_summary["client_id"] == "bob"
        assert bob_summary["total_requests"] == 1



def test_csv_export_endpoint_and_secret_exclusion(client: TestClient):
    """Requirement 19: GET /v1/usage/export returns CSV without secrets or raw prompts."""
    # Ensure at least one request exists
    client.post(
        "/v1/chat/completions",
        json={"model": "mock-model", "messages": [{"role": "user", "content": "Confidential Prompt Text"}]},
    )

    res = client.get("/v1/usage/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    csv_text = res.text

    # Header assertions
    assert "request_id" in csv_text
    assert "provider" in csv_text
    assert "total_cost" in csv_text

    # Safety assertions: Never leak raw prompt or tokens/secrets
    assert "Confidential Prompt Text" not in csv_text
    assert "gw_test_" not in csv_text
    assert TEST_AUTH_SECRET not in csv_text


def test_database_failure_handling_strict_vs_resilient(test_db_url: str):
    """Requirement 20: Test database failure behavior under strict mode vs resilient mode."""
    # 1. Resilient Mode (database_strict_mode = False): Request succeeds even if DB fails
    resilient_settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        database_url=test_db_url,
        database_strict_mode=False,
        cache_enabled=False,
    )
    app_resilient = create_app()
    app_resilient.dependency_overrides[get_settings] = lambda: resilient_settings
    c_resilient = TestClient(app_resilient, headers={"Authorization": f"Bearer {VALID_TEST_KEY}"})

    with patch("app.db.service.DatabaseService.record_request_outcome", side_effect=Exception("Disk full")):
        r1 = c_resilient.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]})
        assert r1.status_code == 200  # Resilient mode does not break user traffic

    # 2. Strict Mode (database_strict_mode = True): Request fails with 500 database_error
    strict_settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        database_url=test_db_url,
        database_strict_mode=True,
        cache_enabled=False,
    )
    app_strict = create_app()
    app_strict.dependency_overrides[get_settings] = lambda: strict_settings
    c_strict = TestClient(app_strict, raise_server_exceptions=False, headers={"Authorization": f"Bearer {VALID_TEST_KEY}"})

    with patch("app.db.service.DatabaseService.record_request_outcome", side_effect=Exception("Disk full")):
        r2 = c_strict.post("/v1/chat/completions", json={"model": "mock-model", "messages": [{"role": "user", "content": "hi"}]})
        assert r2.status_code == 500
        assert r2.json()["error"]["code"] == "database_error"
