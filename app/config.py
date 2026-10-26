"""Application configuration loaded from environment variables."""

import json
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import Field, SecretStr, field_validator, model_validator
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
        "mock-rate-limit",
        "mock-auth-error",
        "mock-server-error",
        "llama3.2:1b",
        "qwen2.5-coder:7b-instruct-q4_K_M",
        "llama3.2",
        "phi3",
        "mistral",
    ]
    default_model: str = "mock-model"
    max_request_size_bytes: int = 1_048_576  # 1 MB default
    max_messages_per_request: int = 50
    max_completion_tokens_limit: int = 4096
    provider_timeout_seconds: float = 5.0
    provider_max_retries: int = 2
    provider_retry_initial_backoff: float = 0.5
    provider_retry_max_backoff: float = 4.0
    log_level: str = "INFO"

    # Restricted Legacy Model Policy (Phase 9.3.2)
    allow_restricted_models: bool = False

    # Authentication Settings (Phase 2)
    auth_enabled: bool = True
    auth_secret: str = ""
    client_keys: List[Dict[str, Any]] = Field(default_factory=list)

    # Provider Selection (Phase 2 & Phase 8)
    active_provider: str = "mock"  # "mock" or "ollama"
    ollama_base_url: str = "http://localhost:11434"

    # Database & Persistence (Phase 3)
    database_url: str = "sqlite:///./data/saferoute.db"
    database_strict_mode: bool = False

    # Redis & Exact-Match Response Caching (Phase 4)
    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = False
    cache_ttl_seconds: int = 300
    cache_namespace: str = "v1"
    cache_failure_policy: str = "fail_open"  # "fail_open" or "fail_closed"

    # Semantic Response Caching (Phase 9.4)
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = 0.85
    semantic_cache_ttl_seconds: int = 300
    semantic_cache_embedding_provider: str = "local"  # "local", "mock", or "sentence_transformers"
    semantic_cache_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    semantic_cache_embedding_version: str = "v1"
    semantic_cache_max_candidates: int = 100
    semantic_cache_temperature_tolerance: float = 0.0
    semantic_cache_failure_policy: str = "fail_open"  # "fail_open" or "fail_closed"

    # Redis-Backed Client Rate Limiting (Phase 5)
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    rate_limit_namespace: str = "v1"
    rate_limit_failure_policy: str = "fail_closed"  # "fail_closed" (secure default) or "fail_open"

    # Configurable Guardrails (Phase 6)
    guardrails_enabled: bool = False
    guardrails_input_enabled: bool = True
    guardrails_output_enabled: bool = True
    guardrails_action: str = "block"  # currently supported: "block"
    guardrails_max_text_length: int = 100_000
    guardrails_rules: List[Dict[str, Any]] = Field(default_factory=list)

    # Semantic Safety Classification and Moderation (Phase 9.5)
    safety_classifier_enabled: bool = False
    safety_classifier_provider: str = "local"  # "local", "mock", "deterministic", "disabled"
    safety_classifier_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    safety_classifier_timeout_seconds: float = 0.5
    safety_classifier_failure_policy: str = "fail_closed"  # "fail_closed" or "fail_open"
    safety_classifier_threshold_injection: float = 0.80
    safety_classifier_threshold_hate: float = 0.80
    safety_classifier_threshold_toxicity: float = 0.80
    safety_classifier_threshold_pii: float = 0.75
    safety_classifier_action_injection: str = "block"  # "block", "flag_and_forward"
    safety_classifier_action_hate: str = "block"  # "block", "flag_and_forward"
    safety_classifier_action_toxicity: str = "block"  # "block", "flag_and_forward"
    safety_classifier_action_pii: str = "redact"  # "redact", "block", "flag_and_forward"
    safety_classifier_inspect_output: bool = True

    # Multi-Provider Failover Settings (Phase 9.1 & 9.1.1)
    failover_enabled: bool = False
    failover_allow_mock_fallback: bool = False
    failover_max_attempts: int = 3
    failover_timeout_budget_seconds: float = 15.0
    failover_retry_delay_seconds: float = 0.5
    failover_max_retry_delay_seconds: float = 5.0
    failover_fallback_models: Dict[str, List[str]] = Field(default_factory=dict)
    failover_eligible_error_codes: List[str] = Field(
        default_factory=lambda: [
            "gateway_timeout",
            "provider_error",
            "provider_rate_limit_error",
            "bad_gateway",
            "service_unavailable",
        ]
    )
    failover_eligible_status_codes: List[int] = Field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )

    # Streaming Settings (Phase 9.2 & Phase 11C)
    streaming_enabled: bool = True
    streaming_cache_replay_enabled: bool = True

    # Prometheus Metrics & Observability (Phase 11B)
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    metrics_require_auth: bool = False
    metrics_auth_token: Optional[str] = None

    # CORS Configuration (Phase 12A / 12C)
    cors_allowed_origins: List[str] = Field(default_factory=lambda: ["*"])

    def get_fallback_models_for(self, model: str) -> List[str]:
        """Return configured fallback models list for a specific model."""
        if model in self.failover_fallback_models:
            return list(self.failover_fallback_models[model])
        if "default" in self.failover_fallback_models:
            return list(self.failover_fallback_models["default"])
        if "*" in self.failover_fallback_models:
            return list(self.failover_fallback_models["*"])
        return []

    def get_client_rate_limits(self, client_id: str) -> Tuple[int, int]:
        """Return (requests, window_seconds) applying any clean per-client override."""
        for client in self.client_keys:
            if isinstance(client, dict) and client.get("client_id") == client_id:
                reqs = client.get("rate_limit_requests", self.rate_limit_requests)
                win = client.get("rate_limit_window_seconds", self.rate_limit_window_seconds)
                return int(reqs), int(win)
        return self.rate_limit_requests, self.rate_limit_window_seconds


    @field_validator("allowed_models", mode="before")
    @classmethod
    def parse_allowed_models(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse comma-separated strings or list/JSON array of allowed models."""
        if isinstance(v, str):
            v_stripped = v.strip()
            if (v_stripped.startswith("'") and v_stripped.endswith("'")) or (v_stripped.startswith('"') and v_stripped.endswith('"')):
                v_stripped = v_stripped[1:-1].strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, list):
                        return [str(m).strip() for m in parsed if str(m).strip()]
                except Exception:
                    pass
            return [m.strip().strip("'\"[]") for m in v_stripped.split(",") if m.strip().strip("'\"[]")]
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
            if (v_stripped.startswith("'") and v_stripped.endswith("'")) or (v_stripped.startswith('"') and v_stripped.endswith('"')):
                v_stripped = v_stripped[1:-1].strip()
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

    @field_validator("auth_secret")
    @classmethod
    def validate_auth_secret(cls, v: str) -> str:
        """Ensure AUTH_SECRET meets minimum security length if provided."""
        if v and len(v.strip()) < 16:
            raise ValueError("AUTH_SECRET must be at least 16 characters long.")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure DATABASE_URL is non-empty and starts with a supported database scheme."""
        if not v or not isinstance(v, str):
            raise ValueError("DATABASE_URL cannot be empty.")
        v_clean = v.strip()
        allowed_schemes = (
            "sqlite://",
            "sqlite+aiosqlite://",
            "postgresql://",
            "postgresql+asyncpg://",
            "mysql://",
        )
        if not any(v_clean.startswith(prefix) for prefix in allowed_schemes):
            raise ValueError(
                f"DATABASE_URL must begin with one of: {', '.join(allowed_schemes)}."
            )
        return v_clean

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, v: str) -> str:
        """Ensure OLLAMA_BASE_URL starts with http:// or https://."""
        if not v or not isinstance(v, str):
            raise ValueError("OLLAMA_BASE_URL cannot be empty.")
        v_clean = v.strip().rstrip("/")
        if not (v_clean.startswith("http://") or v_clean.startswith("https://")):
            raise ValueError("OLLAMA_BASE_URL must begin with http:// or https://.")
        return v_clean

    @field_validator("cache_ttl_seconds")
    @classmethod
    def validate_cache_ttl(cls, v: int) -> int:
        """Ensure cache TTL is a positive integer."""
        if v <= 0:
            raise ValueError("CACHE_TTL_SECONDS must be a positive integer greater than 0.")
        return v

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        """Validate Redis URL format without logging credentials."""
        if not v or not (v.startswith("redis://") or v.startswith("rediss://") or v.startswith("unix://")):
            raise ValueError("REDIS_URL must begin with redis://, rediss://, or unix://.")
        return v

    @field_validator("cache_failure_policy")
    @classmethod
    def validate_cache_failure_policy(cls, v: str) -> str:
        """Ensure cache failure policy is either fail_open or fail_closed."""
        allowed = {"fail_open", "fail_closed"}
        if v.lower() not in allowed:
            raise ValueError(f"CACHE_FAILURE_POLICY must be one of: {', '.join(allowed)}.")
        return v.lower()

    @field_validator("rate_limit_requests")
    @classmethod
    def validate_rate_limit_requests(cls, v: int) -> int:
        """Ensure RATE_LIMIT_REQUESTS is a positive integer greater than 0."""
        if v <= 0:
            raise ValueError("RATE_LIMIT_REQUESTS must be a positive integer greater than 0.")
        return v

    @field_validator("rate_limit_window_seconds")
    @classmethod
    def validate_rate_limit_window_seconds(cls, v: int) -> int:
        """Ensure RATE_LIMIT_WINDOW_SECONDS is a positive integer greater than 0."""
        if v <= 0:
            raise ValueError("RATE_LIMIT_WINDOW_SECONDS must be a positive integer greater than 0.")
        return v

    @field_validator("rate_limit_failure_policy")
    @classmethod
    def validate_rate_limit_failure_policy(cls, v: str) -> str:
        """Ensure RATE_LIMIT_FAILURE_POLICY is either fail_open or fail_closed."""
        allowed = {"fail_open", "fail_closed"}
        if v.lower() not in allowed:
            raise ValueError(f"RATE_LIMIT_FAILURE_POLICY must be one of: {', '.join(allowed)}.")
        return v.lower()

    @field_validator("guardrails_action")
    @classmethod
    def validate_guardrails_action(cls, v: str) -> str:
        """Validate GUARDRAILS_ACTION is a supported action."""
        allowed = {"block"}
        if v.lower() not in allowed:
            raise ValueError(f"GUARDRAILS_ACTION must be one of: {', '.join(allowed)}.")
        return v.lower()

    @field_validator("guardrails_max_text_length")
    @classmethod
    def validate_guardrails_max_text_length(cls, v: int) -> int:
        """Ensure GUARDRAILS_MAX_TEXT_LENGTH is a positive integer greater than 0."""
        if v <= 0:
            raise ValueError("GUARDRAILS_MAX_TEXT_LENGTH must be a positive integer greater than 0.")
        return v

    @field_validator("guardrails_rules", mode="before")
    @classmethod
    def parse_and_validate_guardrails_rules(
        cls, v: Union[str, List[Dict[str, Any]], None]
    ) -> List[Dict[str, Any]]:
        """Parse JSON-encoded string or list of guardrail rule definitions and validate patterns."""
        if v is None:
            return []
        rules = v
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return []
            try:
                rules = json.loads(v_stripped)
            except Exception as exc:
                raise ValueError(f"Invalid JSON format for GUARDRAILS_RULES: {exc}")

        if not isinstance(rules, list):
            raise ValueError("GUARDRAILS_RULES must be a JSON array of rule objects.")

        validated_rules: List[Dict[str, Any]] = []
        allowed_stages = {"both", "input", "output"}
        allowed_match_types = {"regex", "contains", "keyword"}
        allowed_actions = {"block"}

        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise ValueError(f"Guardrail rule at index {idx} must be a dictionary.")

            rule_id = str(rule.get("rule_id", "")).strip()
            if not rule_id:
                raise ValueError(f"Guardrail rule at index {idx} is missing required 'rule_id'.")

            pattern = str(rule.get("pattern", "")).strip()
            if not pattern:
                raise ValueError(f"Guardrail rule '{rule_id}' is missing required 'pattern'.")

            stage = str(rule.get("stage", "both")).lower().strip()
            if stage not in allowed_stages:
                raise ValueError(
                    f"Guardrail rule '{rule_id}' has invalid stage '{stage}'. "
                    f"Must be one of: {', '.join(sorted(allowed_stages))}."
                )

            match_type = str(rule.get("match_type", "regex")).lower().strip()
            if match_type not in allowed_match_types:
                raise ValueError(
                    f"Guardrail rule '{rule_id}' has invalid match_type '{match_type}'. "
                    f"Must be one of: {', '.join(sorted(allowed_match_types))}."
                )

            action = str(rule.get("action", "block")).lower().strip()
            if action not in allowed_actions:
                raise ValueError(
                    f"Guardrail rule '{rule_id}' has unsupported action '{action}'. "
                    f"Must be one of: {', '.join(sorted(allowed_actions))}."
                )

            case_sensitive = bool(rule.get("case_sensitive", False))

            # Validate regex compilation immediately during configuration parsing
            if match_type in ("regex", "keyword"):
                flags = 0 if case_sensitive else re.IGNORECASE
                test_pattern = (
                    rf"\b{re.escape(pattern)}\b" if match_type == "keyword" else pattern
                )
                try:
                    re.compile(test_pattern, flags=flags)
                except re.error as exc:
                    raise ValueError(
                        f"Guardrail rule '{rule_id}' contains invalid regex pattern '{pattern}': {exc}"
                    )

            validated_rules.append({
                "rule_id": rule_id,
                "pattern": pattern,
                "match_type": match_type,
                "case_sensitive": case_sensitive,
                "stage": stage,
                "action": action,
                "description": rule.get("description"),
            })

        return validated_rules

    @field_validator("active_provider")
    @classmethod
    def validate_active_provider(cls, v: str) -> str:
        """Ensure active_provider is either mock or ollama."""
        allowed = {"mock", "ollama"}
        if v.lower() not in allowed:
            raise ValueError(f"ACTIVE_PROVIDER must be one of: {', '.join(sorted(allowed))}.")
        return v.lower()

    @field_validator("failover_fallback_models", mode="before")
    @classmethod
    def parse_failover_fallback_models(
        cls, v: Union[str, Dict[str, Any], List[str], None]
    ) -> Dict[str, List[str]]:
        """Parse dictionary, JSON string, or list into fallback mapping."""
        if v is None:
            return {}
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return {}
            try:
                parsed = json.loads(v_stripped)
                if isinstance(parsed, dict):
                    return {
                        str(k): (list(val) if isinstance(val, (list, tuple)) else [str(val)])
                        for k, val in parsed.items()
                    }
                if isinstance(parsed, list):
                    return {"default": [str(m) for m in parsed]}
            except Exception:
                # Comma-separated list of default fallbacks
                models = [m.strip() for m in v.split(",") if m.strip()]
                return {"default": models}
        if isinstance(v, dict):
            return {
                str(k): (list(val) if isinstance(val, (list, tuple)) else [str(val)])
                for k, val in v.items()
            }
        if isinstance(v, list):
            return {"default": [str(m) for m in v]}
        return {}

    @field_validator("failover_max_attempts")
    @classmethod
    def validate_failover_max_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("FAILOVER_MAX_ATTEMPTS must be an integer >= 1.")
        return v

    @field_validator("failover_timeout_budget_seconds")
    @classmethod
    def validate_failover_timeout_budget(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("FAILOVER_TIMEOUT_BUDGET_SECONDS must be > 0.")
        return v

    @field_validator("failover_eligible_status_codes", mode="before")
    @classmethod
    def parse_failover_status_codes(cls, v: Union[str, List[int]]) -> List[int]:
        if isinstance(v, str):
            return [int(c.strip()) for c in v.split(",") if c.strip()]
        return v

    @field_validator("failover_eligible_error_codes", mode="before")
    @classmethod
    def parse_failover_error_codes(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    @field_validator("semantic_cache_threshold")
    @classmethod
    def validate_semantic_cache_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("SEMANTIC_CACHE_THRESHOLD must be between 0.0 and 1.0.")
        return v

    @field_validator("semantic_cache_embedding_provider")
    @classmethod
    def validate_semantic_cache_embedding_provider(cls, v: str) -> str:
        allowed = {"local", "mock", "deterministic", "test"}
        if v.lower().strip() not in allowed:
            raise ValueError(
                f"SEMANTIC_CACHE_EMBEDDING_PROVIDER must be one of: {', '.join(sorted(allowed))}."
            )
        return v.lower().strip()

    @field_validator("semantic_cache_failure_policy")
    @classmethod
    def validate_semantic_cache_failure_policy(cls, v: str) -> str:
        allowed = {"fail_open", "fail_closed"}
        if v.lower().strip() not in allowed:
            raise ValueError(
                f"SEMANTIC_CACHE_FAILURE_POLICY must be one of: {', '.join(sorted(allowed))}."
            )
        return v.lower().strip()

    @field_validator("safety_classifier_provider")
    @classmethod
    def validate_safety_classifier_provider(cls, v: str) -> str:
        allowed = {"local", "mock", "deterministic", "disabled"}
        if v.lower().strip() not in allowed:
            raise ValueError(
                f"SAFETY_CLASSIFIER_PROVIDER must be one of: {', '.join(sorted(allowed))}."
            )
        return v.lower().strip()

    @field_validator("safety_classifier_failure_policy")
    @classmethod
    def validate_safety_classifier_failure_policy(cls, v: str) -> str:
        allowed = {"fail_open", "fail_closed"}
        if v.lower().strip() not in allowed:
            raise ValueError(
                f"SAFETY_CLASSIFIER_FAILURE_POLICY must be one of: {', '.join(sorted(allowed))}."
            )
        return v.lower().strip()

    @field_validator(
        "safety_classifier_threshold_injection",
        "safety_classifier_threshold_hate",
        "safety_classifier_threshold_toxicity",
        "safety_classifier_threshold_pii",
    )
    @classmethod
    def validate_safety_classifier_thresholds(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("Safety classifier thresholds must be between 0.0 and 1.0.")
        return float(v)

    @field_validator(
        "safety_classifier_action_injection",
        "safety_classifier_action_hate",
        "safety_classifier_action_toxicity",
        "safety_classifier_action_pii",
    )
    @classmethod
    def validate_safety_classifier_actions(cls, v: str) -> str:
        allowed = {"block", "flag_and_forward", "redact"}
        clean = v.lower().strip()
        if clean not in allowed:
            raise ValueError(
                f"Safety classifier action must be one of: {', '.join(sorted(allowed))}."
            )
        return clean

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(
        cls, v: Union[str, List[str], None]
    ) -> List[str]:
        """Parse string, JSON list, or list into allowed CORS origins."""
        if v is None:
            return ["*"]
        if isinstance(v, str):
            v_clean = v.strip()
            if (v_clean.startswith("'") and v_clean.endswith("'")) or (
                v_clean.startswith('"') and v_clean.endswith('"')
            ):
                v_clean = v_clean[1:-1].strip()
            if v_clean.startswith("[") and v_clean.endswith("]"):
                try:
                    parsed = json.loads(v_clean)
                    if isinstance(parsed, list):
                        return [str(o).strip() for o in parsed if str(o).strip()]
                except Exception:
                    pass
            return [o.strip() for o in v_clean.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def validate_operational_safety(self) -> "Settings":
        # 1. Production safety constraints
        if getattr(self, "app_env", "").lower().strip() in ("production", "prod"):
            if not getattr(self, "auth_enabled", True):
                raise ValueError("Authentication cannot be disabled when APP_ENV is 'production'.")

            prov = getattr(self, "semantic_cache_embedding_provider", "").lower().strip()
            if prov in ("mock", "deterministic", "test"):
                raise ValueError(
                    f"Mock embedding provider '{prov}' is strictly forbidden in production environment. "
                    "Set SEMANTIC_CACHE_EMBEDDING_PROVIDER=local."
                )
            if getattr(self, "safety_classifier_enabled", False):
                safety_prov = getattr(self, "safety_classifier_provider", "").lower().strip()
                if safety_prov in ("mock", "deterministic", "test"):
                    raise ValueError(
                        f"Mock safety classifier '{safety_prov}' is strictly forbidden in production. "
                        "Set SAFETY_CLASSIFIER_PROVIDER=local."
                    )

        # 2. Metrics authentication configuration safety
        if getattr(self, "metrics_enabled", True) and getattr(self, "metrics_require_auth", False):
            has_metrics_token = bool(getattr(self, "metrics_auth_token", None))
            has_client_auth = bool(
                getattr(self, "auth_enabled", True)
                and getattr(self, "auth_secret", "")
                and len(getattr(self, "auth_secret", "")) >= 16
            )
            if not has_metrics_token and not has_client_auth:
                raise ValueError(
                    "When METRICS_REQUIRE_AUTH is true, either METRICS_AUTH_TOKEN or a valid "
                    "AUTH_SECRET (>= 16 characters) must be configured."
                )

        return self




@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
