"""
Structured logging configuration for CaseVault.

Call configure_logging() once at application startup (inside the lifespan
handler or before the ASGI app is served).

Log format
----------
Each log record includes:
  - timestamp   (ISO-8601)
  - level       (DEBUG / INFO / WARNING / ERROR / CRITICAL)
  - service     ("casevault")
  - environment (from settings.environment)
  - request_id  (from the per-request ContextVar; "-" when not in a request)
  - logger      (dotted module name)
  - message

Redaction rules
---------------
  Do NOT log:
    - Passwords, JWTs, API keys, or credentials
    - Full document text or retrieved excerpts
    - Complete LLM prompts or model responses
    - Raw user question or answer text
    - Internal file paths or storage keys

  Safe to log:
    - Operation names (e.g. "rag.ask")
    - Durations in milliseconds
    - Counts (chunks retrieved, tool calls made)
    - HTTP method, path, status code
    - Provider / model names (not keys)
    - Success / failure outcomes and safe error categories
"""

import logging
import sys

from app.core.request_context import get_request_id


class _RequestIdFilter(logging.Filter):
    """
    Injects the current request ID into every log record.

    This allows the request_id field to be included in the format string
    without requiring each call site to pass it explicitly.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


class _StructuredFormatter(logging.Formatter):
    """
    Single-line structured log formatter.

    Output:
        2026-10-14T12:00:00.000Z INFO casevault [req-id] app.services.rag - message
    """

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", get_request_id())
        return super().format(record)


_LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s casevault "
    "[%(request_id)s] %(name)s - %(message)s"
)
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure root logging for CaseVault.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Defaults to INFO.  In DEBUG mode more verbose output is shown.

    Safe to call multiple times; subsequent calls reconfigure the root logger.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(_RequestIdFilter())

    formatter = _StructuredFormatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicate output on reconfigure
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
