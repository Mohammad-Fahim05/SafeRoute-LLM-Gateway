"""Pytest fixtures for SafeRoute LLM Gateway test suite."""

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Return test settings with fast timeouts and standard allowed models."""
    return Settings(
        app_env="test",
        allowed_models=["mock-model", "mock-timeout", "mock-error", "mock-malformed"],
        default_model="mock-model",
        max_request_size_bytes=1024 * 1024,
        max_messages_per_request=10,
        max_completion_tokens_limit=2048,
        provider_timeout_seconds=0.2,  # Fast timeout for test suite
        log_level="DEBUG",
    )


@pytest.fixture
def app(test_settings: Settings):
    """Create FastAPI application with test settings override."""
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: test_settings
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Synchronous test client for Starlette/FastAPI."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
