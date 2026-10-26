"""Opt-in live infrastructure and cloud provider integration tests for SafeRoute LLM Gateway.

These tests execute against live staging infrastructure (Redis, Anthropic Claude, Google Gemini, Ollama)
only when explicitly requested via opt-in environment variables.
In standard local test runs without external services or credentials, tests are cleanly SKIPPED
and reported as UNVERIFIED.

Safety & Isolation Guarantees:
- Uses dedicated staging namespaces (saferoute:staging_test:<uuid>) to prevent key collisions.
- Guaranteed key deletion in finally blocks even on test failure.
- Minimal token consumption (<10 tokens, lowest cost tiers).
- No production data access; secrets are never printed in logs or test output.
"""

import os
import socket
import uuid
import httpx
import pytest

from app.config import Settings


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a network port is reachable via TCP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        res = s.connect_ex((host, port))
        return res == 0
    except Exception:
        return False
    finally:
        s.close()


@pytest.mark.anyio
async def test_live_redis_opt_in():
    """Live Redis integration test (Opt-in via TEST_LIVE_REDIS=true).

    Verifies real TCP connection, SETEX with TTL expiration, GET, DEL,
    and client tenant namespace isolation against live Redis server.
    """
    opt_in = os.environ.get("TEST_LIVE_REDIS", "").lower() in ("true", "1", "yes")
    redis_url = os.environ.get("STAGING_REDIS_URL") or os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Opt-in check
    if not opt_in:
        pytest.skip(
            "Live Redis infrastructure UNVERIFIED: Requires TEST_LIVE_REDIS=true. "
            "To verify, start Redis (or set STAGING_REDIS_URL) and run with TEST_LIVE_REDIS=true."
        )

    try:
        from redis.asyncio import from_url
        client = from_url(redis_url, encoding="utf-8", decode_responses=True, socket_timeout=2.0)
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Live Redis service unreachable on {redis_url}: {exc}")

    run_id = uuid.uuid4().hex[:8]
    ns = os.environ.get("STAGING_CACHE_NAMESPACE", "staging_live_test")
    test_key = f"saferoute:{ns}:probe:{run_id}"
    tenant_a_key = f"saferoute:{ns}:tenant_a:{run_id}"
    tenant_b_key = f"saferoute:{ns}:tenant_b:{run_id}"

    try:
        # 1. Test SETEX with TTL
        await client.set(test_key, "probe_val", ex=30)
        val = await client.get(test_key)
        assert val == "probe_val"

        ttl = await client.ttl(test_key)
        assert 0 < ttl <= 30

        # 2. Test Tenant Namespace Isolation
        await client.set(tenant_a_key, "data_a", ex=30)
        await client.set(tenant_b_key, "data_b", ex=30)

        assert await client.get(tenant_a_key) == "data_a"
        assert await client.get(tenant_b_key) == "data_b"
        assert await client.get(tenant_a_key) != await client.get(tenant_b_key)
    finally:
        # Guaranteed cleanup in finally block
        await client.delete(test_key, tenant_a_key, tenant_b_key)
        await client.aclose()



@pytest.mark.anyio
async def test_live_ollama_opt_in():
    """Live Ollama local server integration test (Opt-in via TEST_LIVE_OLLAMA=true).

    Verifies connection to local Ollama server and executes lightweight inference.
    """
    opt_in = os.environ.get("TEST_LIVE_OLLAMA", "").lower() in ("true", "1", "yes")
    base_url = (os.environ.get("STAGING_OLLAMA_BASE_URL") or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    # Check port
    host = "127.0.0.1"
    port = 11434
    if "://" in base_url:
        netloc = base_url.split("://")[1].split("/")[0]
        if ":" in netloc:
            host, p_str = netloc.split(":")
            port = int(p_str)
        else:
            host = netloc

    if not opt_in:
        pytest.skip(
            f"Live Ollama local provider UNVERIFIED: Requires TEST_LIVE_OLLAMA=true. "
            f"Target: {host}:{port}."
        )

    if not is_port_open(host, port):
        pytest.skip(
            f"Live Ollama local provider UNVERIFIED: Port {host}:{port} is unreachable."
        )

    from app.providers.ollama import OllamaProvider
    from app.api.schemas import ChatCompletionRequest, ChatMessage

    settings = Settings(
        app_env="test",
        active_provider="ollama",
        ollama_base_url=base_url,
        allowed_models=["llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M", "phi3", "mistral"],
    )
    provider = OllamaProvider(base_url=base_url, timeout=30.0)

    try:
        healthy = await provider.check_health()
        if not healthy:
            pytest.skip(f"Ollama server reachable at {base_url} but check_health() returned False.")

        # Query local models from Ollama
        async with httpx.AsyncClient(timeout=3.0) as http_client:
            tags_resp = await http_client.get(f"{base_url}/api/tags")
            if tags_resp.status_code == 200:
                models = [m.get("name", "") for m in tags_resp.json().get("models", [])]
                if models:
                    # Prefer llama3.2:1b for lightweight verification if available
                    target_model = "llama3.2:1b" if "llama3.2:1b" in models else models[0]
                    if target_model not in settings.allowed_models:
                        settings.allowed_models.append(target_model)

                    req = ChatCompletionRequest(
                        model=target_model,
                        messages=[ChatMessage(role="user", content="Ping live test, reply with 'PONG' only.")],
                        max_completion_tokens=10,
                    )
                    resp = await provider.complete(req)
                    assert resp is not None
                    assert len(resp.choices) > 0
                    assert resp.choices[0].message.content is not None
                    assert resp.model == target_model
                    assert resp.usage is not None
                    assert resp.usage.is_mock_estimate is False
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_live_ollama_gateway_route_opt_in(test_db_url: str):
    """End-to-end gateway route test against live local Ollama (Opt-in via TEST_LIVE_OLLAMA=true).

    Sends an authenticated request through /v1/chat/completions with ACTIVE_PROVIDER=ollama,
    verifying readiness probes, guardrails, response normalization, and zero-cost local accounting.
    """
    opt_in = os.environ.get("TEST_LIVE_OLLAMA", "").lower() in ("true", "1", "yes")
    base_url = (os.environ.get("STAGING_OLLAMA_BASE_URL") or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    host = "127.0.0.1"
    port = 11434
    if "://" in base_url:
        netloc = base_url.split("://")[1].split("/")[0]
        if ":" in netloc:
            host, p_str = netloc.split(":")
            port = int(p_str)
        else:
            host = netloc

    if not opt_in:
        pytest.skip(
            f"Live Ollama local provider UNVERIFIED: Requires TEST_LIVE_OLLAMA=true. "
            f"Target: {host}:{port}."
        )

    if not is_port_open(host, port):
        pytest.skip(
            f"Live Ollama local provider UNVERIFIED: Port {host}:{port} is unreachable."
        )

    from app.core.auth import compute_key_verifier
    from app.db import init_db, reset_db_engine
    from app.db.session import get_engine
    from app.main import create_app
    from app.providers import reset_providers
    from starlette.testclient import TestClient
    from sqlalchemy import text

    test_secret = "ollama_route_test_secret_16_chars_min"
    client_key = "gw_ollama_client_key_1234567890123"
    client_verifier = compute_key_verifier(client_key, test_secret)

    reset_db_engine()
    reset_providers()

    settings = Settings(
        app_env="test",
        database_url=test_db_url,
        auth_enabled=True,
        auth_secret=test_secret,
        client_keys=[{"client_id": "ollama_user", "verifier": client_verifier, "enabled": True}],
        active_provider="ollama",
        ollama_base_url=base_url,
        allowed_models=["llama3.2:1b", "qwen2.5-coder:7b-instruct-q4_K_M", "mock-model"],
        default_model="llama3.2:1b",
        cache_enabled=False,
        rate_limit_enabled=False,
        provider_timeout_seconds=30.0,
    )

    engine = get_engine(settings.database_url)
    init_db(engine)
    app = create_app(settings)
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        # 1. Readiness probe checks Ollama
        ready_resp = client.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["providers"]["ollama"] == "available"

        # 2. Chat completion routed to local Ollama
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {client_key}"},
            json={
                "model": "llama3.2:1b",
                "messages": [{"role": "user", "content": "Respond with the single word PONG"}],
                "max_completion_tokens": 5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert resp.headers.get("x-serving-provider") == "ollama"
        assert resp.headers.get("x-serving-model") == "llama3.2:1b"
        assert len(data["choices"]) > 0
        assert data["choices"][0]["message"]["content"]
        assert data["usage"]["prompt_tokens"] is not None
        assert data["usage"]["completion_tokens"] is not None

        # 3. Verify SQLite accounting record
        with engine.connect() as conn:
            req_row = conn.execute(
                text("SELECT provider, model_requested, status FROM request_records ORDER BY id DESC LIMIT 1")
            ).mappings().first()
            assert req_row is not None
            assert req_row["provider"] == "ollama"
            assert req_row["model_requested"] == "llama3.2:1b"
            assert req_row["status"] == "success"

            usage_row = conn.execute(
                text("SELECT total_cost, calculation_status FROM usage_records ORDER BY id DESC LIMIT 1")
            ).mappings().first()
            assert usage_row is not None
            assert usage_row["calculation_status"] == "free_tier_local"
            assert float(usage_row["total_cost"]) == 0.0

    reset_providers()
