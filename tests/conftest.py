"""Pytest fixtures for SafeRoute LLM Gateway test suite."""

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.main import create_app

VALID_TEST_KEY = "gw_test_valid_key_for_testing_1234567890"
DISABLED_TEST_KEY = "gw_test_disabled_key_for_testing_99999999"
NON_ADMIN_TEST_KEY = "gw_test_non_admin_client_key_55555555"
TEST_AUTH_SECRET = "test_auth_secret_minimum_16_characters_long"

VALID_KEY_VERIFIER = compute_key_verifier(VALID_TEST_KEY, TEST_AUTH_SECRET)
DISABLED_KEY_VERIFIER = compute_key_verifier(DISABLED_TEST_KEY, TEST_AUTH_SECRET)
NON_ADMIN_KEY_VERIFIER = compute_key_verifier(NON_ADMIN_TEST_KEY, TEST_AUTH_SECRET)


@pytest.fixture
def test_db_url(tmp_path) -> str:
    """Create isolated temporary SQLite database for each test function."""
    db_file = tmp_path / "test_saferoute.db"
    return f"sqlite:///{db_file}"



@pytest.fixture
def test_settings(test_db_url: str) -> Settings:
    """Return test settings with authentication enabled, fast timeouts, and test keys."""
    return Settings(
        app_env="test",
        allowed_models=[
            "mock-model",
            "mock-timeout",
            "mock-error",
            "mock-malformed",
            "llama3.2:1b",
            "phi3",
        ],
        default_model="mock-model",
        max_request_size_bytes=1024 * 1024,
        max_messages_per_request=10,
        max_completion_tokens_limit=2048,
        provider_timeout_seconds=0.2,  # Fast timeout for test suite
        log_level="DEBUG",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[
            {"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True, "role": "admin", "is_admin": True},
            {"client_id": "tenant_client", "verifier": NON_ADMIN_KEY_VERIFIER, "enabled": True, "role": "client", "is_admin": False},
            {"client_id": "revoked_client", "verifier": DISABLED_KEY_VERIFIER, "enabled": False, "role": "client", "is_admin": False},
        ],
        active_provider="mock",
        database_url=test_db_url,
        database_strict_mode=False,
        cache_enabled=False,
    )


@pytest.fixture
def app(test_settings: Settings):
    """Create FastAPI application with test settings override and initialized DB."""
    reset_db_engine()
    from app.db.session import get_engine
    init_db(get_engine(test_settings.database_url))

    application = create_app(test_settings)
    application.dependency_overrides[get_settings] = lambda: test_settings
    return application



@pytest.fixture
def client(app) -> TestClient:
    """Synchronous test client configured with valid Bearer credentials by default."""
    with TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {VALID_TEST_KEY}"},
    ) as test_client:
        yield test_client


@pytest.fixture
def non_admin_client(app) -> TestClient:
    """Synchronous test client configured with tenant/non-admin client credentials."""
    with TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {NON_ADMIN_TEST_KEY}"},
    ) as test_client:
        yield test_client


@pytest.fixture
def unauthenticated_client(app) -> TestClient:
    """Synchronous test client with no Authorization credentials."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
