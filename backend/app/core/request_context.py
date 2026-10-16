"""
Per-request context propagation using contextvars.

Each request receives a unique ID that is stored in a ContextVar so it
is available throughout the call stack without being passed explicitly.
The ID is set by RequestIDMiddleware and reset after the response.

Usage:
    from app.core.request_context import get_request_id

    logger.info("doing work", extra={"request_id": get_request_id()})

Design notes
------------
- ContextVar is task-scoped in asyncio, so concurrent requests never
  share the same value.
- The default "-" is returned when called outside a request context
  (e.g. startup tasks, background jobs, unit tests).
- Incoming X-Request-ID headers are accepted only when they match the
  safe pattern (alphanumeric + hyphens, 1–64 chars).  Invalid headers
  are replaced with a freshly generated UUID4 to prevent log injection.
"""

import re
import uuid
from contextvars import ContextVar

# HTTP header name used to carry the request ID
REQUEST_ID_HEADER = "X-Request-ID"

# Pattern for safe inbound request IDs (alphanumeric and hyphens only)
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")

# ContextVar — default "-" when accessed outside a request context
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Return the request ID for the current context, or '-' if not set."""
    return request_id_var.get()


def generate_request_id() -> str:
    """Generate a new random request ID."""
    return str(uuid.uuid4())


def is_safe_request_id(value: str) -> bool:
    """
    Return True if *value* is a safe, accepted inbound request ID.

    Accepts 1–64 characters consisting only of ASCII letters, digits, and
    hyphens.  Rejects anything that could introduce log-injection characters
    (newlines, quotes, semicolons, etc.).
    """
    return bool(_SAFE_ID_RE.match(value))
