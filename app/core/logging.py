"""Structured, safe logging for SafeRoute LLM Gateway."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.request_context import get_request_id


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter producing structured log entries."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }

        # Include structured extra fields if provided
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            # Ensure no sensitive content is included
            safe_extra = {
                k: v
                for k, v in record.extra_data.items()
                if not any(
                    secret_term in k.lower()
                    for secret_term in ["token", "key", "secret", "password", "prompt", "content"]
                )
            }
            log_obj.update(safe_extra)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure root logger with structured JSON formatting."""
    root_logger = logging.getLogger("saferoute")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Avoid duplicate handlers on re-initialization
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        root_logger.addHandler(handler)

    root_logger.propagate = False
    return root_logger


logger = setup_logging()
