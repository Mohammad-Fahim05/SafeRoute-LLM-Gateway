"""Gateway client authentication and HMAC-SHA256 key verification."""

import hashlib
import hmac
import secrets
from typing import Optional, Tuple
from fastapi import Depends, Header

from app.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.core.logging import logger
from app.core.request_context import get_request_id, set_client_id

KEY_PREFIX = "gw_test_"


def generate_api_key() -> str:
    """Generate a high-entropy client API key with a recognizable prefix."""
    token = secrets.token_urlsafe(32)
    return f"{KEY_PREFIX}{token}"


def compute_key_verifier(plaintext_key: str, auth_secret: str) -> str:
    """Compute keyed HMAC-SHA256 digest of a plaintext key."""
    if not auth_secret or len(auth_secret) < 16:
        raise ValueError("auth_secret must be at least 16 characters long.")
    return hmac.new(
        auth_secret.encode("utf-8"),
        plaintext_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract and validate Bearer token from Authorization header."""
    if not authorization:
        raise AuthenticationError("Missing Authorization header.")

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthenticationError("Invalid Authorization header format. Expected 'Bearer <key>'.")

    token = parts[1].strip()
    if not token:
        raise AuthenticationError("Bearer token cannot be empty.")

    return token


def authenticate_client(
    plaintext_key: str, settings: Settings
) -> Tuple[str, bool]:
    """Verify key against configured client verifiers.
    
    Returns (client_id, enabled).
    """
    if not settings.auth_secret:
        logger.error("Authentication failed closed: AUTH_SECRET is not configured.")
        raise AuthenticationError("Gateway authentication is misconfigured.")

    try:
        computed_verifier = compute_key_verifier(plaintext_key, settings.auth_secret)
    except Exception as exc:
        logger.error(f"Error computing key verifier: {exc}")
        raise AuthenticationError("Gateway authentication error.")

    # Constant-time comparison against configured client verifiers
    for client in settings.client_keys:
        expected_verifier = client.get("verifier", "")
        if hmac.compare_digest(computed_verifier, expected_verifier):
            is_enabled = bool(client.get("enabled", False))
            client_id = str(client.get("client_id", "unknown"))
            return client_id, is_enabled

    raise AuthenticationError("Invalid client API key.")


async def verify_api_key(
    authorization: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """FastAPI dependency enforcing client API key authentication."""

    # Allow disabling auth for isolated local debugging with clear warning
    if not settings.auth_enabled:
        logger.warning(
            "Authentication is explicitly disabled in settings. This mode is not secure for exposed services!"
        )
        set_client_id("anonymous_dev")
        return "anonymous_dev"

    token = extract_bearer_token(authorization)
    client_id, is_enabled = authenticate_client(token, settings)

    if not is_enabled:
        logger.warning(
            f"Authentication rejected for disabled or revoked client: {client_id}",
            extra={"extra_data": {"client_id": client_id}},
        )
        raise AuthenticationError("Client API key is disabled or revoked.")

    set_client_id(client_id)
    return client_id
