"""Application configuration loaded from environment variables."""

import json
from functools import lru_cache
from typing import Any, Dict, List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for SafeRoute LLM Gateway."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    allowed_models: List[str] = [
        "mock-model",
        "mock-timeout",
        "mock-error",
        "mock-malformed",
        "llama3.2:1b",
        "llama3.2",
        "phi3",
        "mistral",
    ]
    default_model: str = "mock-model"
    max_request_size_bytes: int = 1_048_576  # 1 MB default
    max_messages_per_request: int = 50
    max_completion_tokens_limit: int = 4096
    provider_timeout_seconds: float = 5.0
    log_level: str = "INFO"

    # Authentication Settings (Phase 2)
    auth_enabled: bool = True
    auth_secret: str = ""
    client_keys: List[Dict[str, Any]] = Field(default_factory=list)

    # Provider Selection (Phase 2)
    active_provider: str = "mock"  # "mock" or "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"

    @field_validator("allowed_models", mode="before")
    @classmethod
    def parse_allowed_models(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse comma-separated strings or list of allowed models."""
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v

    @field_validator("client_keys", mode="before")
    @classmethod
    def parse_client_keys(
        cls, v: Union[str, List[Dict[str, Any]], None]
    ) -> List[Dict[str, Any]]:
        """Parse JSON-encoded string or list of client key dictionaries."""
        if v is None:
            return []
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return []
            try:
                parsed = json.loads(v_stripped)
                if isinstance(parsed, list):
                    return parsed
                raise ValueError("CLIENT_KEYS must be a JSON array of objects.")
            except Exception as exc:
                raise ValueError(f"Invalid JSON format for client_keys: {exc}")
        return v


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
