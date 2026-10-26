"""Integration tests for Ollama provider routing and model execution."""

import json
import httpx
from starlette.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from tests.conftest import TEST_AUTH_SECRET, VALID_KEY_VERIFIER, VALID_TEST_KEY


def test_authenticated_ollama_request_with_mocked_transport(test_db_url: str):
    """Requirement 18: Authenticated Ollama requests work via mocked HTTP transport."""
    from app.db import init_db
    from app.db.session import get_engine, reset_db_engine

    reset_db_engine()
    init_db(get_engine(test_db_url))

    def ollama_mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.34.0"})

        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            assert body["model"] == "llama3.2:1b"
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2:1b",
                    "created_at": "2026-10-24T18:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": "Hello from mocked local Ollama instance!",
                    },
                    "done": True,
                    "prompt_eval_count": 12,
                    "eval_count": 20,
                },
            )
        return httpx.Response(404, text="Not Found")

    # Set up settings with active_provider = "ollama"
    ollama_settings = Settings(
        app_env="test",
        database_url=test_db_url,
        active_provider="ollama",
        allowed_models=["llama3.2:1b", "mock-model"],
        auth_enabled=True,
        auth_secret=TEST_AUTH_SECRET,
        client_keys=[{"client_id": "test_client", "verifier": VALID_KEY_VERIFIER, "enabled": True}],
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: ollama_settings

    # Inject mock HTTP client into Ollama provider
    from app.providers import get_ollama_provider
    provider = get_ollama_provider(ollama_settings)
    mock_http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(ollama_mock_handler),
        base_url="http://localhost:11434",
    )
    provider._client = mock_http_client

    client = TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Authorization": f"Bearer {VALID_TEST_KEY}"},
    )

    payload = {
        "model": "llama3.2:1b",
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "temperature": 0.7,
    }

    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "llama3.2:1b"
    assert data["choices"][0]["message"]["content"] == "Hello from mocked local Ollama instance!"
    assert data["usage"]["prompt_tokens"] == 12
    assert data["usage"]["completion_tokens"] == 20
    assert data["usage"]["is_mock_estimate"] is False


def test_unknown_model_rejected_for_ollama(client: TestClient):
    """Requirement 19: Unknown model is rejected with HTTP 400 even when provider is configured."""
    payload = {
        "model": "completely-unauthorized-model",
        "messages": [{"role": "user", "content": "Hi"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_model"


def test_authenticated_mock_request_still_works(client: TestClient):
    """Requirement 17: Authenticated mock requests continue to work deterministically."""
    payload = {
        "model": "mock-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "mock-model"
    assert "SafeRoute mock provider" in data["choices"][0]["message"]["content"]
    assert data["usage"]["is_mock_estimate"] is True
