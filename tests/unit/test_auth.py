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


def test_extract_bearer_token_tolerates_raw_gateway_key():
    """Verify raw keys starting with gw_test_ prefix are accepted without Bearer keyword."""
    key = "gw_test_abcdef1234567890"
    assert extract_bearer_token(key) == key
    assert extract_bearer_token(f"  {key}  ") == key


@pytest.mark.anyio
async def test_verify_api_key_bearer_dependency():
    """Verify verify_api_key dependency authenticates valid Bearer credentials."""
    from unittest.mock import MagicMock
    from fastapi.security import HTTPAuthorizationCredentials
    from app.core.auth import verify_api_key

    secret = "a_very_secure_test_secret_12345"
    key = "gw_test_bearer_valid"
    verifier = compute_key_verifier(key, secret)
    settings = Settings(
        auth_secret=secret,
        auth_enabled=True,
        client_keys=[{"client_id": "client_bearer", "verifier": verifier, "enabled": True}],
    )

    request = MagicMock()
    request.headers.get.return_value = None
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=key)

    client_id = await verify_api_key(request=request, credentials=creds, settings=settings)
    assert client_id == "client_bearer"


@pytest.mark.anyio
async def test_verify_api_key_raw_header_dependency():
    """Verify verify_api_key dependency extracts raw key from request headers."""
    from unittest.mock import MagicMock
    from app.core.auth import verify_api_key

    secret = "a_very_secure_test_secret_12345"
    key = "gw_test_raw_valid"
    verifier = compute_key_verifier(key, secret)
    settings = Settings(
        auth_secret=secret,
        auth_enabled=True,
        client_keys=[{"client_id": "client_raw", "verifier": verifier, "enabled": True}],
    )

    request = MagicMock()
    request.headers.get.return_value = key

    client_id = await verify_api_key(request=request, credentials=None, settings=settings)
    assert client_id == "client_raw"


@pytest.mark.anyio
async def test_verify_api_key_disabled_client_rejected():
    """Verify verify_api_key rejects disabled client with 401 AuthenticationError."""
    from unittest.mock import MagicMock
    from fastapi.security import HTTPAuthorizationCredentials
    from app.core.auth import verify_api_key

    secret = "a_very_secure_test_secret_12345"
    key = "gw_test_disabled"
    verifier = compute_key_verifier(key, secret)
    settings = Settings(
        auth_secret=secret,
        auth_enabled=True,
        client_keys=[{"client_id": "client_disabled", "verifier": verifier, "enabled": False}],
    )

    request = MagicMock()
    request.headers.get.return_value = None
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=key)

    with pytest.raises(AuthenticationError, match="disabled or revoked"):
        await verify_api_key(request=request, credentials=creds, settings=settings)


@pytest.mark.anyio
async def test_verify_api_key_mismatched_key_rejected():
    """Verify verify_api_key rejects invalid key."""
    from unittest.mock import MagicMock
    from fastapi.security import HTTPAuthorizationCredentials
    from app.core.auth import verify_api_key

    secret = "a_very_secure_test_secret_12345"
    settings = Settings(
        auth_secret=secret,
        auth_enabled=True,
        client_keys=[{"client_id": "client_ok", "verifier": "correct_verifier", "enabled": True}],
    )

    request = MagicMock()
    request.headers.get.return_value = None
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="gw_test_wrong")

    with pytest.raises(AuthenticationError, match="Invalid client API key"):
        await verify_api_key(request=request, credentials=creds, settings=settings)


def test_openapi_security_scheme_configuration():
    """Verify OpenAPI generates HTTPBearer security scheme for Swagger UI."""
    from app.main import create_app

    app = create_app()
    schema = app.openapi()

    assert "components" in schema
    assert "securitySchemes" in schema["components"]
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["type"] == "http"
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"

    post_op = schema["paths"]["/v1/chat/completions"]["post"]
    assert post_op.get("security") == [{"HTTPBearer": []}]
    param_names = [p.get("name") for p in post_op.get("parameters", [])]
    assert "authorization" not in param_names
    assert "settings" not in param_names
