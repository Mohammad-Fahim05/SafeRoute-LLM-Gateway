"""Request context management using contextvars."""

import re
import uuid
from contextvars import ContextVar
from typing import Optional

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_SAFE_REQUEST_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def set_request_id(request_id: Optional[str] = None) -> str:
    """Validate or generate a safe request ID and store it in contextvar."""
    if request_id and _SAFE_REQUEST_ID_REGEX.match(request_id):
        clean_id = request_id
    else:
        clean_id = f"req_{uuid.uuid4().hex}"

    _request_id_ctx.set(clean_id)
    return clean_id


def get_request_id() -> str:
    """Retrieve the current request ID from contextvar."""
    rid = _request_id_ctx.get()
    if not rid:
        # Fallback if accessed outside of standard middleware pipeline
        rid = f"req_{uuid.uuid4().hex}"
        _request_id_ctx.set(rid)
    return rid


_client_id_ctx: ContextVar[str] = ContextVar("client_id", default="")


def set_client_id(client_id: Optional[str] = None) -> str:
    """Store the authenticated client ID in contextvar."""
    cid = client_id or "anonymous"
    _client_id_ctx.set(cid)
    return cid


def get_client_id() -> str:
    """Retrieve the authenticated client ID from contextvar."""
    return _client_id_ctx.get() or "anonymous"
