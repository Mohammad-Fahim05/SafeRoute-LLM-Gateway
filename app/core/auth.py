"""Gateway client authentication and HMAC-SHA256 key verification."""

import hashlib
import hmac
import secrets
from typing import Optional, Tuple
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.core.logging import logger
from app.core.request_context import get_request_id, set_client_id

KEY_PREFIX = "gw_test_"

bearer_scheme = HTTPBearer(auto_error=False)


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
    """Extract and validate Bearer token from Authorization header.

    Accepts standard 'Bearer <key>' format as well as raw key strings
    beginning with KEY_PREFIX for client convenience.
    """
    if not authorization:
        raise AuthenticationError("Missing Authorization header.")

    auth_str = authorization.strip()
    if not auth_str:
        raise AuthenticationError("Missing Authorization header.")

    # Tolerant fallback: accept raw key if it starts with the expected prefix
    if auth_str.startswith(KEY_PREFIX):
        return auth_str

    parts = auth_str.split(" ", 1)
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


def get_client_auth_details(plaintext_key: str, settings: Settings) -> dict:
    """Verify key against configured client verifiers and return full client metadata.

    Returns dict with keys: client_id, enabled, role, is_admin.
    """
    if not settings.auth_secret:
        logger.error("Authentication failed closed: AUTH_SECRET is not configured.")
        raise AuthenticationError("Gateway authentication is misconfigured.")

    clean_key = plaintext_key.strip()
    if clean_key.lower().startswith("bearer "):
        clean_key = clean_key[7:].strip()

    try:
        computed_verifier = compute_key_verifier(clean_key, settings.auth_secret)
    except Exception as exc:
        logger.error(f"Error computing key verifier: {exc}")
        raise AuthenticationError("Gateway authentication error.")

    for client in settings.client_keys:
        expected_verifier = client.get("verifier", "")
        if hmac.compare_digest(computed_verifier, expected_verifier):
            is_enabled = bool(client.get("enabled", False))
            client_id = str(client.get("client_id", "unknown"))
            explicit_is_admin = client.get("is_admin")
            explicit_role = client.get("role")
            if explicit_is_admin is not None:
                is_admin = bool(explicit_is_admin)
                role = str(explicit_role) if explicit_role else ("admin" if is_admin else "client")
            elif explicit_role is not None:
                role = str(explicit_role).lower()
                is_admin = role == "admin"
            else:
                is_admin = client_id.lower() in ("admin", "local_dev", "root")
                role = "admin" if is_admin else "client"

            return {
                "client_id": client_id,
                "enabled": is_enabled,
                "role": role,
                "is_admin": is_admin,
            }

    raise AuthenticationError("Invalid client API key.")


async def verify_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
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

    token: str
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
    else:
        raw_header = request.headers.get("authorization")
        token = extract_bearer_token(raw_header)

    client_id, is_enabled = authenticate_client(token, settings)

    if not is_enabled:
        logger.warning(
            f"Authentication rejected for disabled or revoked client: {client_id}",
            extra={"extra_data": {"client_id": client_id}},
        )
        raise AuthenticationError("Client API key is disabled or revoked.")

    set_client_id(client_id)
    return client_id


async def verify_client_auth_details(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    """FastAPI dependency verifying client credentials and returning full auth metadata."""
    if not settings.auth_enabled:
        set_client_id("anonymous_dev")
        return {
            "client_id": "anonymous_dev",
            "enabled": True,
            "role": "admin",
            "is_admin": True,
        }

    token: str
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
    else:
        raw_header = request.headers.get("authorization")
        token = extract_bearer_token(raw_header)

    auth_details = get_client_auth_details(token, settings)

    if not auth_details["enabled"]:
        client_id = auth_details["client_id"]
        logger.warning(
            f"Authentication rejected for disabled or revoked client: {client_id}",
            extra={"extra_data": {"client_id": client_id}},
        )
        raise AuthenticationError("Client API key is disabled or revoked.")

    set_client_id(auth_details["client_id"])
    return auth_details


async def verify_admin_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict:
    """FastAPI dependency requiring administrator privileges for privileged management actions."""
    from fastapi import HTTPException, status

    auth_details = await verify_client_auth_details(request, credentials, settings)
    if not auth_details.get("is_admin"):
        client_id = auth_details.get("client_id")
        logger.warning(
            f"Administrative action forbidden for regular client: {client_id}",
            extra={"extra_data": {"client_id": client_id}},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to access this resource.",
        )
    return auth_details



async def verify_metrics_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """Enforce authorization for Prometheus /metrics endpoint if configured.

    If settings.metrics_require_auth is False (default for internal scraper access),
    access is permitted without credentials.
    If True, validates against settings.metrics_auth_token or valid client keys.
    """
    if not settings.metrics_require_auth:
        return

    token: str
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
    else:
        raw_header = request.headers.get("authorization")
        try:
            token = extract_bearer_token(raw_header)
        except AuthenticationError:
            raise AuthenticationError("Missing or invalid Authorization header for metrics access.")

    # 1. Dedicated metrics auth token comparison if configured
    if settings.metrics_auth_token:
        if not hmac.compare_digest(token, settings.metrics_auth_token):
            logger.warning("Metrics access rejected: invalid metrics_auth_token.")
            raise AuthenticationError("Invalid metrics authorization token.")
        return

    # 2. Standard client API key validation fallback
    client_id, is_enabled = authenticate_client(token, settings)
    if not is_enabled:
        raise AuthenticationError("Client key is disabled for metrics access.")
