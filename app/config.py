"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import List, Union
from pydantic import field_validator
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
    ]
    default_model: str = "mock-model"
    max_request_size_bytes: int = 1_048_576  # 1 MB default
    max_messages_per_request: int = 50
    max_completion_tokens_limit: int = 4096
    provider_timeout_seconds: float = 5.0
    log_level: str = "INFO"

    @field_validator("allowed_models", mode="before")
    @classmethod
    def parse_allowed_models(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse comma-separated strings or list of allowed models."""
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
