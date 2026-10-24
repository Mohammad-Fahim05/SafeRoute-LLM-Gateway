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
