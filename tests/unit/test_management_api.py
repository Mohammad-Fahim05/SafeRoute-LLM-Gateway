"""Unit and integration tests for SafeRoute Management Console API."""

import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.db import db_service


def test_management_auth_status(client: TestClient):
    """Verify /api/management/auth/status endpoint reports gateway authentication configuration."""
    response = client.get("/api/management/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert "auth_enabled" in data
    assert data["key_prefix"] == "gw_test_"
    assert "registered_clients_count" in data


def test_management_overview_telemetry(client: TestClient):
    """Verify /api/management/overview computes KPIs from durable SQLite records."""
    response = client.get("/api/management/overview")
    assert response.status_code == 200
    data = response.json()

    assert "total_requests" in data
    assert "successful_requests" in data
    assert "failed_requests" in data
    assert "success_rate" in data
    assert "avg_duration_ms" in data
    assert "p50_duration_ms" in data
    assert "p95_duration_ms" in data
    assert "p99_duration_ms" in data
    assert "exact_cache_hits" in data
    assert "semantic_cache_hits" in data
    assert "cache_hit_rate" in data
    assert "total_tokens" in data
    assert "estimated_total_cost" in data
    assert "provider_counts" in data
    assert "model_counts" in data
    assert "status_counts" in data
    assert "timeline" in data
    assert "recent_requests" in data


def test_management_list_requests_pagination(client: TestClient):
    """Verify /api/management/requests returns paginated and filterable records."""
    response = client.get("/api/management/requests?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert "total_pages" in data

    if data["items"]:
        first = data["items"][0]
        assert "request_id" in first
        assert "model_requested" in first
        assert "provider" in first
        assert "status" in first
        assert "duration_ms" in first
        assert "cache_status" in first


def test_management_request_detail(client: TestClient):
    """Verify /api/management/requests/{request_id} returns detailed audit trail."""
    # First get an existing request ID from list
    list_resp = client.get("/api/management/requests?page=1&page_size=1")
    items = list_resp.json().get("items", [])
    if items:
        rid = items[0]["request_id"]
        detail_resp = client.get(f"/api/management/requests/{rid}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["request_id"] == rid
        assert "attempts" in detail
        assert "retention_notice" in detail

    # Non-existent ID returns 404
    missing_resp = client.get("/api/management/requests/non_existent_id_99999")
    assert missing_resp.status_code == 404


def test_management_database_overview(client: TestClient):
    """Verify /api/management/database/overview returns schema metadata safely."""
    response = client.get("/api/management/database/overview")
    assert response.status_code == 200
    data = response.json()

    assert "database_url" in data
    assert "journal_mode" in data
    assert "tables" in data
    assert data["read_only"] is True

    table_names = [t["table_name"] for t in data["tables"]]
    assert "request_records" in table_names
    assert "usage_records" in table_names
    assert "clients" in table_names


def test_management_table_records_whitelisting(client: TestClient):
    """Verify /api/management/database/tables/{table}/records enforces strict table whitelist."""
    # Whitelisted table succeeds
    ok_resp = client.get("/api/management/database/tables/clients/records?page=1&page_size=5")
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["table_name"] == "clients"
    assert "records" in data

    # Non-whitelisted table is rejected with 400
    bad_resp = client.get("/api/management/database/tables/malicious_table_injection/records")
    assert bad_resp.status_code == 400
    assert "not permitted for inspection" in bad_resp.json()["detail"]


def test_management_cache_telemetry(client: TestClient):
    """Verify /api/management/cache returns exact and semantic cache statuses."""
    response = client.get("/api/management/cache")
    assert response.status_code == 200
    data = response.json()

    assert "redis_connected" in data
    assert "exact_cache" in data
    assert "semantic_cache" in data
    assert "total_cache_hits" in data
    assert "overall_hit_rate" in data


def test_management_providers_status(client: TestClient):
    """Verify /api/management/providers returns Ollama and Mock configuration."""
    response = client.get("/api/management/providers")
    assert response.status_code == 200
    data = response.json()

    assert "active_provider" in data
    assert "ollama" in data
    assert "mock" in data
    assert "allowed_models" in data
    assert "capabilities" in data
    assert "failover" in data


def test_management_sanitized_config(client: TestClient):
    """Verify /api/management/config redacts sensitive secrets."""
    response = client.get("/api/management/config")
    assert response.status_code == 200
    data = response.json()

    assert "app_env" in data
    assert "active_provider" in data
    assert "cache" in data
    assert "rate_limiting" in data
    assert "guardrails" in data
    # Ensure no secret strings leaked
    assert "auth_secret" not in data
    assert "client_keys" not in data
    assert "redis_password" not in data


def test_management_system_health_summary(client: TestClient):
    """Verify /api/management/health/summary returns overall system health status."""
    response = client.get("/api/management/health/summary")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ("healthy", "degraded", "unavailable")
    assert data["gateway"] == "healthy"
    assert "database" in data
    assert "redis" in data
    assert "ollama" in data


def test_management_unauthenticated_requests_fail(unauthenticated_client: TestClient):
    """Verify management endpoints strictly reject requests lacking Authorization header."""
    assert unauthenticated_client.get("/api/management/overview").status_code == 401
    assert unauthenticated_client.get("/api/management/requests").status_code == 401
    assert unauthenticated_client.get("/api/management/database/overview").status_code == 401
    assert unauthenticated_client.get("/api/management/config").status_code == 401
    assert unauthenticated_client.get("/api/management/cache").status_code == 401


def test_management_auth_verify_endpoint(
    client: TestClient,
    unauthenticated_client: TestClient,
):
    """Verify /api/management/auth/verify endpoint validates keys and returns role details."""
    from tests.conftest import (
        VALID_TEST_KEY,
        NON_ADMIN_TEST_KEY,
        DISABLED_TEST_KEY,
    )

    # Valid admin key
    resp_admin = unauthenticated_client.post(
        "/api/management/auth/verify",
        json={"api_key": VALID_TEST_KEY},
    )
    assert resp_admin.status_code == 200
    data_admin = resp_admin.json()
    assert data_admin["valid"] is True
    assert data_admin["client_id"] == "test_client"
    assert data_admin["is_admin"] is True
    assert data_admin["role"] == "admin"

    # Valid non-admin key
    resp_non_admin = unauthenticated_client.post(
        "/api/management/auth/verify",
        json={"api_key": NON_ADMIN_TEST_KEY},
    )
    assert resp_non_admin.status_code == 200
    data_non_admin = resp_non_admin.json()
    assert data_non_admin["valid"] is True
    assert data_non_admin["client_id"] == "tenant_client"
    assert data_non_admin["is_admin"] is False
    assert data_non_admin["role"] == "client"

    # Revoked / disabled key
    resp_disabled = unauthenticated_client.post(
        "/api/management/auth/verify",
        json={"api_key": DISABLED_TEST_KEY},
    )
    assert resp_disabled.status_code == 200
    assert resp_disabled.json()["valid"] is False

    # Completely invalid key
    resp_invalid = unauthenticated_client.post(
        "/api/management/auth/verify",
        json={"api_key": "gw_test_completely_bogus_key_99999"},
    )
    assert resp_invalid.status_code == 200
    assert resp_invalid.json()["valid"] is False


def test_management_authorization_boundaries_non_admin(non_admin_client: TestClient):
    """Verify non-admin client keys are restricted: 403 on privileged endpoints, scoped on overview."""
    # 1. Privileged database endpoints return 403 Forbidden
    db_resp = non_admin_client.get("/api/management/database/overview")
    assert db_resp.status_code == 403
    assert "Administrative privileges required" in db_resp.json()["detail"]

    # 2. Privileged database table record inspection returns 403 Forbidden
    table_resp = non_admin_client.get("/api/management/database/tables/clients/records")
    assert table_resp.status_code == 403
    assert "Administrative privileges required" in table_resp.json()["detail"]

    # 3. Privileged config inspection returns 403 Forbidden
    config_resp = non_admin_client.get("/api/management/config")
    assert config_resp.status_code == 403
    assert "Administrative privileges required" in config_resp.json()["detail"]

    # 4. Standard client endpoints succeed (200 OK)
    overview_resp = non_admin_client.get("/api/management/overview")
    assert overview_resp.status_code == 200

    requests_resp = non_admin_client.get("/api/management/requests")
    assert requests_resp.status_code == 200
