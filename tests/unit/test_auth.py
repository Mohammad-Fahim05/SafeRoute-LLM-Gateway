"""Unit tests for authentication logic, HMAC verification, and key management."""

import pytest
from app.config import Settings
from app.core.auth import (
    KEY_PREFIX,
    authenticate_client,
    compute_key_verifier,
    extract_bearer_token,
    generate_api_key,
)
from app.core.errors import AuthenticationError


def test_generate_api_key_format():
    """Verify generated key has expected prefix and entropy."""
    key1 = generate_api_key()
    key2 = generate_api_key()
    assert key1.startswith(KEY_PREFIX)
    assert key2.startswith(KEY_PREFIX)
    assert key1 != key2
    assert len(key1) > len(KEY_PREFIX) + 20


def test_compute_key_verifier_deterministic():
    """Verify HMAC-SHA256 verifier computation is deterministic."""
    secret = "a_very_secure_test_secret_12345"
    key = "gw_test_example_key_value"
    v1 = compute_key_verifier(key, secret)
    v2 = compute_key_verifier(key, secret)
    assert v1 == v2
    assert len(v1) == 64  # SHA-256 hex string


def test_compute_key_verifier_rejects_weak_secret():
    """Verify secrets under 16 characters are rejected."""
    with pytest.raises(ValueError, match="at least 16 characters"):
        compute_key_verifier("gw_test_key", "too_short")


def test_extract_bearer_token():
    """Verify parsing valid and invalid Authorization header values."""
    assert extract_bearer_token("Bearer my_token") == "my_token"
    assert extract_bearer_token("bearer  my_token ") == "my_token"

    # Missing / None
    with pytest.raises(AuthenticationError, match="Missing Authorization"):
        extract_bearer_token(None)

    # Empty
    with pytest.raises(AuthenticationError, match="Missing Authorization"):
        extract_bearer_token("")

    # Malformed prefix
    with pytest.raises(AuthenticationError, match="Invalid Authorization header format"):
        extract_bearer_token("Basic dXNlcjpwYXNz")

    with pytest.raises(AuthenticationError, match="Invalid Authorization header format"):
        extract_bearer_token("Token my_token")

    # Missing token part
    with pytest.raises(AuthenticationError, match="Invalid Authorization header format"):
        extract_bearer_token("Bearer")


def test_authenticate_client_valid():
    """Verify valid key returns client_id and enabled flag."""
    secret = "a_very_secure_test_secret_12345"
    key = "gw_test_valid_client_key"
    verifier = compute_key_verifier(key, secret)

    settings = Settings(
        auth_secret=secret,
        client_keys=[{"client_id": "client_alpha", "verifier": verifier, "enabled": True}],
    )

    client_id, is_enabled = authenticate_client(key, settings)
    assert client_id == "client_alpha"
    assert is_enabled is True


def test_authenticate_client_disabled():
    """Verify disabled client key returns enabled=False."""
    secret = "a_very_secure_test_secret_12345"
    key = "gw_test_revoked_key"
    verifier = compute_key_verifier(key, secret)

    settings = Settings(
        auth_secret=secret,
        client_keys=[{"client_id": "client_revoked", "verifier": verifier, "enabled": False}],
    )

    client_id, is_enabled = authenticate_client(key, settings)
    assert client_id == "client_revoked"
    assert is_enabled is False


def test_authenticate_client_invalid_key():
    """Verify unrecognized key raises AuthenticationError."""
    secret = "a_very_secure_test_secret_12345"
    settings = Settings(
        auth_secret=secret,
        client_keys=[{"client_id": "client_alpha", "verifier": "different_hash", "enabled": True}],
    )

    with pytest.raises(AuthenticationError, match="Invalid client API key"):
        authenticate_client("gw_test_unrecognized_key", settings)


def test_authenticate_client_missing_auth_secret_fails_closed():
    """Verify missing auth secret fails closed with AuthenticationError."""
    settings = Settings(auth_secret="")
    with pytest.raises(AuthenticationError, match="misconfigured"):
        authenticate_client("gw_test_any_key", settings)
