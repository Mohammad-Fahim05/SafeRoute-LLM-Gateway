"""Unit tests for configuration loading and validation."""

import os
from app.config import Settings


def test_default_settings():
    """Verify sensible default configuration values."""
    settings = Settings()
    assert settings.app_env in ["development", "test"]
    assert "mock-model" in settings.allowed_models
    assert settings.provider_timeout_seconds > 0
    assert settings.max_request_size_bytes > 0


def test_allowed_models_parsing_from_string():
    """Verify that comma-separated model strings are cleanly parsed into lists."""
    settings = Settings(allowed_models="model-a, model-b , model-c")
    assert settings.allowed_models == ["model-a", "model-b", "model-c"]


def test_allowed_models_from_list():
    """Verify list values are preserved as-is."""
    settings = Settings(allowed_models=["custom-1", "custom-2"])
    assert settings.allowed_models == ["custom-1", "custom-2"]


def test_auth_cannot_be_disabled_in_production():
    """Verify that authentication cannot be accidentally disabled in production environment."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        Settings(app_env="production", auth_enabled=False)
    assert "Authentication cannot be disabled when APP_ENV is 'production'" in str(exc.value)


def test_auth_secret_minimum_length_validation():
    """Verify that short auth secrets (< 16 chars) fail validation with a clear error."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        Settings(auth_secret="too-short")
    assert "AUTH_SECRET must be at least 16 characters long" in str(exc.value)

    # Valid secret length passes cleanly
    s = Settings(auth_secret="this_is_a_sufficiently_long_auth_secret_12345")
    assert s.auth_secret == "this_is_a_sufficiently_long_auth_secret_12345"


def test_database_url_validation():
    """Verify database URL scheme validation and error on invalid scheme."""
    import pytest
    from pydantic import ValidationError

    # Supported schemes pass
    s1 = Settings(database_url="sqlite:///./data/saferoute.db")
    assert s1.database_url == "sqlite:///./data/saferoute.db"

    s2 = Settings(database_url="postgresql://user:pass@localhost:5432/saferoute")
    assert s2.database_url.startswith("postgresql://")

    # Unsupported or empty scheme fails
    with pytest.raises(ValidationError) as exc1:
        Settings(database_url="ftp://localhost/db")
    assert "DATABASE_URL must begin with one of" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        Settings(database_url="")
    assert "DATABASE_URL cannot be empty" in str(exc2.value)


def test_ollama_base_url_validation():
    """Verify Ollama base URL validation."""
    import pytest
    from pydantic import ValidationError

    # Valid HTTP/HTTPS passes
    s1 = Settings(ollama_base_url="http://localhost:11434")
    assert s1.ollama_base_url == "http://localhost:11434"

    s2 = Settings(ollama_base_url="https://remote-ollama.internal:11434/")
    assert s2.ollama_base_url == "https://remote-ollama.internal:11434"

    # Missing scheme or invalid scheme fails
    with pytest.raises(ValidationError) as exc1:
        Settings(ollama_base_url="localhost:11434")
    assert "OLLAMA_BASE_URL must begin with http:// or https://" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        Settings(ollama_base_url="")
    assert "OLLAMA_BASE_URL cannot be empty" in str(exc2.value)


def test_metrics_require_auth_validation():
    """Verify that enabling metrics_require_auth requires either token or client auth configuration."""
    import pytest
    from pydantic import ValidationError

    # Missing both token and auth secret fails
    with pytest.raises(ValidationError) as exc:
        Settings(metrics_require_auth=True, metrics_auth_token=None, auth_secret="")
    assert "When METRICS_REQUIRE_AUTH is true" in str(exc.value)

    # Configured with dedicated metrics_auth_token passes
    s1 = Settings(metrics_require_auth=True, metrics_auth_token="scrape-token-12345", auth_secret="")
    assert s1.metrics_auth_token == "scrape-token-12345"

    # Configured with valid auth_secret passes
    s2 = Settings(
        metrics_require_auth=True,
        metrics_auth_token=None,
        auth_secret="valid_auth_secret_minimum_16_chars_long",
    )
    assert s2.metrics_require_auth is True


def test_cors_allowed_origins_parsing():
    """Verify parsing of CORS allowed origins from string, JSON array, and defaults."""
    # Default is wildcard
    s_default = Settings()
    assert s_default.cors_allowed_origins == ["*"]

    # Comma-separated string
    s_str = Settings(cors_allowed_origins="https://app.example.com, https://admin.example.com")
    assert s_str.cors_allowed_origins == ["https://app.example.com", "https://admin.example.com"]

    # JSON array string
    s_json = Settings(cors_allowed_origins='["https://app.example.com", "https://web.internal"]')
    assert s_json.cors_allowed_origins == ["https://app.example.com", "https://web.internal"]

    # List of strings
    s_list = Settings(cors_allowed_origins=["https://local.dev:3000"])
    assert s_list.cors_allowed_origins == ["https://local.dev:3000"]
