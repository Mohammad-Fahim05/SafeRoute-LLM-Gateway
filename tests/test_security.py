"""Comprehensive Automated Security and Client Isolation Test Suite for SafeRoute LLM Gateway.

Covers:
- Missing authorization (HTTP 401)
- Invalid credentials (HTTP 401)
- Revoked credential rejection (HTTP 401)
- Non-admin access to administrative endpoints returns HTTP 403
- Cross-tenant request detail isolation (Client A cannot read Client B's request details -> 403)
- Cross-tenant request list isolation (Client A cannot see Client B's request records)
- Cross-tenant cache isolation (Client B cannot retrieve Client A's cached response)
- Oversized payload rejection (HTTP 413)
- Unauthorized configuration and database inspection rejection
- Error response sanitization (no internal HMAC secrets, API keys, or raw stack traces disclosed)
"""

import json
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.main import create_app

# Isolated test credentials
AUTH_SECRET = "security_suite_secret_minimum_32_characters_for_hmac!"

KEY_ADMIN = "gw_test_sec_admin_key_1111111111111111111111"
KEY_ALICE = "gw_test_sec_alice_key_2222222222222222222222"
KEY_BOB = "gw_test_sec_bob_key_3333333333333333333333"
KEY_REVOKED = "gw_test_sec_revoked_key_444444444444444444"

VERIFIER_ADMIN = compute_key_verifier(KEY_ADMIN, AUTH_SECRET)
VERIFIER_ALICE = compute_key_verifier(KEY_ALICE, AUTH_SECRET)
VERIFIER_BOB = compute_key_verifier(KEY_BOB, AUTH_SECRET)
VERIFIER_REVOKED = compute_key_verifier(KEY_REVOKED, AUTH_SECRET)


def build_security_app(test_db_url: str, cache_enabled: bool = False, max_size: int = 1024):
    """Build isolated FastAPI app and settings configured for security tests."""
    reset_db_engine()
    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        database_strict_mode=False,
        auth_enabled=True,
        auth_secret=AUTH_SECRET,
        client_keys=[
            {"client_id": "admin_tenant", "verifier": VERIFIER_ADMIN, "enabled": True, "role": "admin", "is_admin": True},
            {"client_id": "alice_tenant", "verifier": VERIFIER_ALICE, "enabled": True, "role": "client", "is_admin": False},
            {"client_id": "bob_tenant", "verifier": VERIFIER_BOB, "enabled": True, "role": "client", "is_admin": False},
            {"client_id": "revoked_tenant", "verifier": VERIFIER_REVOKED, "enabled": False, "role": "client", "is_admin": False},
        ],
        allowed_models=["mock-model"],
        default_model="mock-model",
        active_provider="mock",
        cache_enabled=cache_enabled,
        max_request_size_bytes=max_size,
        rate_limit_enabled=False,
        safety_classifier_enabled=False,
    )
    init_db(get_engine(settings.database_url))
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    if cache_enabled:
        from app.api.routes import get_cache
        from app.cache.redis_cache import ExactResponseCache
        from tests.unit.test_cache import FakeAsyncRedis
        fake_redis = FakeAsyncRedis()
        exact_cache = ExactResponseCache(redis_client=fake_redis, settings=settings)
        app.dependency_overrides[get_cache] = lambda: exact_cache

    return app, settings


def test_missing_authorization_returns_401(test_db_url: str):
    """Security Requirement: Requests without credentials must receive HTTP 401."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers
        data = resp.json()
        assert data["error"]["code"] == "invalid_api_key"
        assert AUTH_SECRET not in resp.text


def test_invalid_credentials_returns_401(test_db_url: str):
    """Security Requirement: Forged or invalid credentials must be rejected with HTTP 401."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer gw_test_forged_unauthorized_token_99999"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"]["code"] == "invalid_api_key"
        assert AUTH_SECRET not in resp.text


def test_revoked_credentials_rejected_with_401(test_db_url: str):
    """Security Requirement: Disabled or revoked client credentials must receive HTTP 401."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_REVOKED}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Hello"}]},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"]["code"] == "invalid_api_key"
        assert "disabled or revoked" in data["error"]["message"].lower()


def test_non_admin_access_to_administrative_endpoints_returns_403(test_db_url: str):
    """Security Requirement: Non-admin client attempting to access admin endpoints receives HTTP 403."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        # 1. Config endpoint
        r_cfg = client.get(
            "/api/management/config",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
        )
        assert r_cfg.status_code == 403
        assert "administrative privileges required" in r_cfg.json()["detail"].lower()

        # 2. Database overview endpoint
        r_db = client.get(
            "/api/management/database/overview",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
        )
        assert r_db.status_code == 403

        # 3. Database table record browser
        r_tbl = client.get(
            "/api/management/database/tables/clients/records",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
        )
        assert r_tbl.status_code == 403

        # Admin key succeeds on all three
        admin_cfg = client.get("/api/management/config", headers={"Authorization": f"Bearer {KEY_ADMIN}"})
        assert admin_cfg.status_code == 200
        admin_db = client.get("/api/management/database/overview", headers={"Authorization": f"Bearer {KEY_ADMIN}"})
        assert admin_db.status_code == 200


def test_cross_tenant_request_isolation(test_db_url: str):
    """Security Requirement: Client A cannot read Client B's request details or history."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        # Alice creates a request
        r_alice = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Alice private prompt"}]},
        )
        assert r_alice.status_code == 200
        alice_rid = r_alice.headers["X-Request-ID"]

        # Bob creates a request
        r_bob = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_BOB}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": "Bob private prompt"}]},
        )
        assert r_bob.status_code == 200
        bob_rid = r_bob.headers["X-Request-ID"]

        # 1. Alice can read her own request detail
        r_alice_detail = client.get(
            f"/api/management/requests/{alice_rid}",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
        )
        assert r_alice_detail.status_code == 200
        assert r_alice_detail.json()["client_id"] == "alice_tenant"

        # 2. Bob CANNOT read Alice's request detail (must return 403 Forbidden)
        r_cross = client.get(
            f"/api/management/requests/{alice_rid}",
            headers={"Authorization": f"Bearer {KEY_BOB}"},
        )
        assert r_cross.status_code == 403
        assert "belongs to another client" in r_cross.json()["detail"].lower()

        # 3. Bob's request list contains only Bob's request, never Alice's
        r_bob_list = client.get(
            "/api/management/requests",
            headers={"Authorization": f"Bearer {KEY_BOB}"},
        )
        assert r_bob_list.status_code == 200
        bob_records = r_bob_list.json()["items"]
        returned_ids = [rec["request_id"] for rec in bob_records]
        assert bob_rid in returned_ids
        assert alice_rid not in returned_ids


def test_cross_tenant_cache_isolation(test_db_url: str):
    """Security Requirement: Client B cannot retrieve Client A's cached response."""
    import uuid
    uid = uuid.uuid4().hex[:8]
    prompt = f"Identical confidential company policy query {uid}"

    app, _ = build_security_app(test_db_url, cache_enabled=True)
    with TestClient(app) as client:
        # Alice sends request -> Misses cache, gets populated
        r_alice = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": prompt}]},
        )
        assert r_alice.status_code == 200
        assert r_alice.headers.get("X-Cache") in ("MISS", None)

        # Alice sends same request again -> Hits cache
        r_alice_hit = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": prompt}]},
        )
        assert r_alice_hit.status_code == 200
        assert r_alice_hit.headers.get("X-Cache") == "HIT"

        # Bob sends the exact same prompt -> Must NOT get Alice's cached response!
        # Client isolation requires client_id in cache key -> Bob gets MISS
        r_bob = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_BOB}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": prompt}]},
        )
        assert r_bob.status_code == 200
        assert r_bob.headers.get("X-Cache") == "MISS"


def test_oversized_payload_rejection_returns_413(test_db_url: str):
    """Security Requirement: Requests exceeding max_request_size_bytes return HTTP 413."""
    # Set maximum request size to 256 bytes
    app, _ = build_security_app(test_db_url, max_size=256)
    with TestClient(app) as client:
        oversized_content = "X" * 1024  # 1 KB > 256 bytes
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
            json={"model": "mock-model", "messages": [{"role": "user", "content": oversized_content}]},
        )
        assert resp.status_code == 413
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        data = resp.json()
        assert data["error"]["code"] == "payload_too_large"


def test_unauthorized_config_and_database_access(test_db_url: str):
    """Security Requirement: Anonymous calls to management config and database return HTTP 401."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        r_cfg = client.get("/api/management/config")
        assert r_cfg.status_code == 401

        r_db = client.get("/api/management/database/overview")
        assert r_db.status_code == 401

        r_records = client.get("/api/management/database/tables/clients/records")
        assert r_records.status_code == 401


def test_error_responses_never_disclose_secrets(test_db_url: str):
    """Security Requirement: Error responses must never leak HMAC secrets, credentials, or traces."""
    app, _ = build_security_app(test_db_url)
    with TestClient(app) as client:
        # 1. Bad JSON schema validation error (422)
        r_422 = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY_ALICE}"},
            json={"model": "mock-model", "temperature": 99.0},  # temperature out of range
        )
        assert r_422.status_code == 422
        body_422 = r_422.text
        assert AUTH_SECRET not in body_422
        assert KEY_ALICE not in body_422
        assert VERIFIER_ALICE not in body_422
        assert "Traceback" not in body_422

        # 2. Simulated internal error (500)
        with patch("app.api.routes.execute_with_failover", side_effect=RuntimeError("Internal test explosion")):
            r_500 = client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {KEY_ALICE}"},
                json={"model": "mock-model", "messages": [{"role": "user", "content": "hello"}]},
            )
            assert r_500.status_code == 500
            body_500 = r_500.text
            assert AUTH_SECRET not in body_500
            assert "Traceback" not in body_500
            assert "Internal test explosion" not in body_500
            assert r_500.headers.get("X-Content-Type-Options") == "nosniff"
            assert r_500.headers.get("X-Frame-Options") == "DENY"
