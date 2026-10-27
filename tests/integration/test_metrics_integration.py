"""Integration tests for Prometheus metrics scraping and request tracking."""

import pytest
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.metrics import reset_metrics
from tests.conftest import VALID_TEST_KEY


@pytest.fixture(autouse=True)
def clean_gateway_metrics():
    """Reset global metrics registry before each test to guarantee fresh counts."""
    reset_metrics()
    yield
    reset_metrics()


def test_metrics_endpoint_public_by_default(client: TestClient):
    """Verify /metrics endpoint responds with Prometheus exposition format."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert any(v in response.headers.get("content-type", "") for v in ("version=0.0.4", "version=1.0.0"))


    body = response.text
    assert "# HELP saferoute_requests_total" in body
    assert "# TYPE saferoute_requests_total counter"
    assert "# HELP saferoute_request_duration_seconds" in body
    assert "# TYPE saferoute_request_duration_seconds histogram"
    assert "# HELP saferoute_streaming_requests_active" in body
    assert "# TYPE saferoute_streaming_requests_active gauge"


def test_metrics_endpoint_disabled_returns_404(app, test_settings: Settings):
    """Verify /metrics returns 404 when disabled via settings."""
    test_settings.metrics_enabled = False
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as local_client:
        response = local_client.get("/metrics")
        assert response.status_code == 404
        assert "disabled" in response.text.lower()


def test_metrics_auth_with_dedicated_token(app, test_settings: Settings):
    """Verify metrics authentication using a dedicated METRICS_AUTH_TOKEN."""
    test_settings.metrics_require_auth = True
    test_settings.metrics_auth_token = "scrape-secret-token-12345"
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app, raise_server_exceptions=False) as unauth_client:
        # 1. No Authorization header -> 401
        res1 = unauth_client.get("/metrics")
        assert res1.status_code == 401

        # 2. Invalid token -> 401
        res2 = unauth_client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
        assert res2.status_code == 401

        # 3. Valid token -> 200
        res3 = unauth_client.get("/metrics", headers={"Authorization": "Bearer scrape-secret-token-12345"})
        assert res3.status_code == 200
        assert "# HELP saferoute_requests_total" in res3.text


def test_metrics_auth_fallback_to_client_keys(app, test_settings: Settings):
    """Verify metrics authentication falls back to registered client keys when no dedicated token is set."""
    test_settings.metrics_require_auth = True
    test_settings.metrics_auth_token = None
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app, raise_server_exceptions=False) as local_client:
        # 1. No credentials -> 401
        res1 = local_client.get("/metrics")
        assert res1.status_code == 401

        # 2. Invalid client key -> 401
        res2 = local_client.get("/metrics", headers={"Authorization": "Bearer gw_test_invalid_99999"})
        assert res2.status_code == 401

        # 3. Valid client key -> 200
        res3 = local_client.get("/metrics", headers={"Authorization": f"Bearer {VALID_TEST_KEY}"})
        assert res3.status_code == 200
        assert "# HELP saferoute_requests_total" in res3.text


def test_metrics_request_lifecycle_and_counts(client: TestClient, unauthenticated_client: TestClient):
    """Verify end-to-end request metrics accurately count success, 401, and 400 requests."""
    # 1. Health check (200, gateway)
    h_res = client.get("/health")
    assert h_res.status_code == 200

    # 2. Authenticated valid chat completion (200, mock)
    chat_res = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Hello SafeRoute"}],
        },
    )
    assert chat_res.status_code == 200

    # 3. Unauthenticated request (401, gateway)
    unauth_res = unauthenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert unauth_res.status_code == 401

    # 4. Invalid model request (400, gateway)
    invalid_res = client.post(
        "/v1/chat/completions",
        json={
            "model": "non-existent-prohibited-model",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert invalid_res.status_code == 400

    # 5. Check /metrics output
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200
    metrics_text = metrics_res.text

    assert 'saferoute_requests_total{provider="gateway",route="/health",status="200"} 1.0' in metrics_text
    assert 'saferoute_requests_total{provider="mock",route="/v1/chat/completions",status="200"} 1.0' in metrics_text
    assert 'saferoute_requests_total{provider="gateway",route="/v1/chat/completions",status="401"} 1.0' in metrics_text
    assert 'saferoute_requests_total{provider="gateway",route="/v1/chat/completions",status="400"} 1.0' in metrics_text

    # Verify duration histograms observed
    assert 'saferoute_request_duration_seconds_count{route="/health",status="200"} 1.0' in metrics_text
    assert 'saferoute_request_duration_seconds_count{route="/v1/chat/completions",status="200"} 1.0' in metrics_text

    # Verify tokens recorded
    assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="input"}' in metrics_text
    assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="output"}' in metrics_text


def test_metrics_provider_error_tracking(client: TestClient):
    """Verify provider timeout errors are tracked in saferoute_provider_errors_total."""
    # Call mock-timeout model (simulates provider timeout)
    res = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-timeout",
            "messages": [{"role": "user", "content": "Will timeout"}],
        },
    )
    # Gateway returns 504 gateway_timeout
    assert res.status_code in (504, 502)

    metrics_res = client.get("/metrics")
    metrics_text = metrics_res.text

    assert 'saferoute_provider_errors_total{error_type="timeout",provider="mock"} 1.0' in metrics_text


def test_metrics_streaming_request(client: TestClient):
    """Verify streaming completion gauge lifecycle and token tracking."""
    stream_res = client.post(
        "/v1/chat/completions",
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Stream me a story"}],
            "stream": True,
        },
    )
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers.get("content-type", "")

    # Iterate complete stream
    events = list(stream_res.iter_lines())
    assert len(events) > 0

    metrics_res = client.get("/metrics")
    metrics_text = metrics_res.text

    # Active streams should be back to 0.0 after stream conclusion
    assert "saferoute_streaming_requests_active 0.0" in metrics_text
    # Cache bypass should be incremented for streaming
    assert 'saferoute_cache_operations_total{cache_type="exact",event="bypass"} 1.0' in metrics_text


def test_metrics_guardrail_block_tracking(app, test_settings: Settings):
    """Verify input guardrail rejections increment saferoute_guardrail_blocks_total."""
    test_settings.guardrails_enabled = True
    test_settings.guardrails_rules = [
        {
            "rule_id": "block-secret-word",
            "match_type": "contains",
            "pattern": "secret_classified_project",
            "case_sensitive": False,
        }
    ]
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app, headers={"Authorization": f"Bearer {VALID_TEST_KEY}"}) as local_client:
        res = local_client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-model",
                "messages": [{"role": "user", "content": "Tell me about secret_classified_project"}],
            },
        )
        assert res.status_code == 400

        metrics_res = local_client.get("/metrics")
        assert 'saferoute_guardrail_blocks_total{detector="rule",stage="input"} 1.0' in metrics_res.text


def test_metrics_payload_too_large(client: TestClient):
    """Verify payload too large (413) records to requests_total and guardrail detector."""
    large_body = "x" * (1024 * 1024 + 500)
    res = client.post(
        "/v1/chat/completions",
        content=large_body,
        headers={"Content-Length": str(len(large_body))},
    )
    assert res.status_code == 413

    metrics_res = client.get("/metrics")
    assert 'saferoute_requests_total{provider="gateway",route="/v1/chat/completions",status="413"} 1.0' in metrics_res.text
    assert 'saferoute_guardrail_blocks_total{detector="payload_size",stage="input"} 1.0' in metrics_res.text


def test_metrics_cache_miss_and_hit_operations(test_db_url: str):
    """Verify exact cache miss and hit metrics and zero double-counting of provider tokens on hits."""
    from app.cache.redis_cache import ExactResponseCache, get_cache
    from app.db import init_db, reset_db_engine
    from app.db.session import get_engine
    from app.main import create_app
    from tests.conftest import TEST_AUTH_SECRET, VALID_KEY_VERIFIER, VALID_TEST_KEY
    from tests.unit.test_cache import FakeAsyncRedis

    settings = Settings(
        app_env="test",
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
        allowed_models=["mock-model"],
        database_url=test_db_url,
        cache_enabled=True,
        cache_ttl_seconds=300,
        provider_timeout_seconds=0.5,
    )
    reset_db_engine()
    init_db(get_engine(settings.database_url))

    fake_redis = FakeAsyncRedis()
    cache_instance = ExactResponseCache(redis_client=fake_redis, settings=settings)

    app_instance = create_app()
    app_instance.dependency_overrides[get_settings] = lambda: settings
    app_instance.dependency_overrides[get_cache] = lambda: cache_instance

    with TestClient(app_instance, headers={"Authorization": f"Bearer {VALID_TEST_KEY}"}) as local_client:
        payload = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
        }

        # 1. First request: Cache MISS
        r1 = local_client.post("/v1/chat/completions", json=payload)
        assert r1.status_code == 200
        assert r1.headers.get("X-Cache") == "MISS"

        # Check metrics after miss
        m1 = local_client.get("/metrics").text
        assert 'saferoute_cache_operations_total{cache_type="exact",event="miss"} 1.0' in m1

        # Extract tokens recorded after miss
        # Input: 3 tokens (estimated by mock), Output: 16 tokens
        assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="input"} 3.0' in m1
        assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="output"} 16.0' in m1

        # 2. Second request: Cache HIT
        r2 = local_client.post("/v1/chat/completions", json=payload)
        assert r2.status_code == 200
        assert r2.headers.get("X-Cache") == "HIT"

        # Check metrics after hit
        m2 = local_client.get("/metrics").text
        assert 'saferoute_cache_operations_total{cache_type="exact",event="hit"} 1.0' in m2

        # CRITICAL: Verify tokens were NOT double-counted on cache hit!
        # Token values must remain exactly 3.0 and 16.0, NOT 6.0 and 32.0
        assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="input"} 3.0' in m2
        assert 'saferoute_tokens_total{model="mock-model",provider="mock",source="mock_estimated",type="output"} 16.0' in m2
