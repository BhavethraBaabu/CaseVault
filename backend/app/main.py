"""
CaseVault FastAPI application entry point.

Security controls (Day 8)
--------------------------
  _BodySizeLimitMiddleware   — Rejects requests whose Content-Length header
                               exceeds settings.max_request_body_bytes before
                               the body is read.  Does not cover chunked
                               transfer-encoding (no Content-Length header);
                               endpoint-level validators remain the backstop.

  _SecurityHeadersMiddleware — Adds defensive HTTP response headers:
                               X-Content-Type-Options, X-Frame-Options,
                               Referrer-Policy.

  Startup check              — Logs a CRITICAL warning if SECRET_KEY matches
                               a known insecure default value.

  CORS                       — Origin list is configurable via CORS_ORIGINS
                               env var (comma-separated or JSON array).
                               Defaults to http://localhost:3000 only.

  API docs gating            — /docs and /redoc are disabled when
                               DOCS_ENABLED=false (recommended in production).

Observability additions (Day 9)
--------------------------------
  _RequestIDMiddleware       — Assigns a unique X-Request-ID to every request.
                               Accepts a client-supplied ID if it matches the
                               safe pattern (alphanumeric + hyphens, 1–64
                               chars); generates a UUID4 otherwise.
                               Stores the ID in a ContextVar for use by
                               structured logging throughout the call stack.
                               Resets the ContextVar after the response.

  configure_logging()        — Installs a structured log formatter that
                               includes timestamp, level, service, environment,
                               request_id, and logger name.

  Exception handlers         — Global handlers for RequestValidationError and
                               unexpected exceptions.  Both return safe JSON
                               bodies (no tracebacks) and include the
                               request_id for correlation.
"""

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api.v1.agent import router as agent_router
from app.api.v1.auth import router as auth_router
from app.api.v1.cases import router as cases_router
from app.api.v1.chat import router as chat_router
from app.api.v1.clients import router as clients_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.search import router as search_router
from app.api.v1.timeline import router as timeline_router
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.request_context import (
    REQUEST_ID_HEADER,
    generate_request_id,
    is_safe_request_id,
    request_id_var,
)

# Configure structured logging immediately so startup messages use the format
configure_logging(log_level=settings.log_level)

logger = logging.getLogger(__name__)

# Known insecure default values for SECRET_KEY.
# A startup warning is emitted if the configured key matches any of these.
_KNOWN_WEAK_KEYS: frozenset[str] = frozenset(
    {
        "change-me-before-production",
        "secret",
        "dev-secret",
        "development",
        "",
    }
)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    """
    Startup checks run before the application begins accepting requests.

    Current checks:
    - SECRET_KEY is not a known insecure default.
    """
    if settings.secret_key in _KNOWN_WEAK_KEYS:
        logger.critical(
            "SECRET_KEY is set to a known insecure default value (%r). "
            "Sessions can be forged.  Set a strong random value before "
            "deploying to production: "
            "python -c \"import secrets; print(secrets.token_hex(32))\"",
            settings.secret_key[:8] + "...",
        )
    logger.info(
        "CaseVault starting",
        extra={
            "version": settings.app_version,
            "environment": settings.environment,
        },
    )
    yield
    logger.info("CaseVault shutting down")


# ---------------------------------------------------------------------------
# Security middlewares
# ---------------------------------------------------------------------------


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Reject requests whose declared Content-Length exceeds the configured limit.

    This provides an early-exit before the request body is read into memory,
    protecting all endpoints from oversized JSON payloads.

    Limitation: requests using chunked transfer-encoding (no Content-Length)
    are not caught here.  Endpoint-level size validation (e.g. validate_file)
    remains the authoritative backstop for those cases.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        cl_header = request.headers.get("content-length")
        if cl_header is not None:
            try:
                if int(cl_header) > settings.max_request_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large."},
                    )
            except ValueError:
                # Malformed Content-Length — let FastAPI/Starlette handle it.
                pass
        return await call_next(request)


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add defensive HTTP response headers to every response.

    Headers added:
    - X-Content-Type-Options: nosniff — prevents MIME-type sniffing.
    - X-Frame-Options: DENY         — blocks framing (clickjacking defence).
    - Referrer-Policy                — limits referrer information leakage.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response


class _RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assign a unique request ID to every request.

    Behaviour:
    1. If the incoming request carries an X-Request-ID header whose value
       matches the safe pattern (ASCII letters, digits, hyphens; 1–64 chars),
       that value is used as-is.
    2. Otherwise a fresh UUID4 is generated.
    3. The ID is stored in a ContextVar so structured loggers can include it
       without explicit passing.
    4. The ContextVar token is reset after the response, even on error.
    5. The ID is echoed back in the X-Request-ID response header.

    Concurrent requests each set their own ContextVar token so they never
    share request IDs accidentally.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        req_id = incoming if is_safe_request_id(incoming) else generate_request_id()

        token = request_id_var.set(req_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = req_id
        return response


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="CaseVault — Legal Case Management Platform API",
    # API docs disabled when DOCS_ENABLED=false (recommended in production).
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    lifespan=_lifespan,
)

# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request,
    exc: RequestValidationError,  # noqa: ARG001
) -> JSONResponse:
    """
    Handle FastAPI/Pydantic request validation errors (HTTP 422).

    Returns a safe, generic message instead of exposing raw validation
    details (which may reference field names or internal schema details).
    Includes the request_id for correlation with server-side logs.
    """
    req_id = request_id_var.get()
    logger.warning(
        "Request validation error on %s %s",
        request.method,
        request.url.path,
        extra={"request_id": req_id},
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error.", "request_id": req_id},
    )


@app.exception_handler(Exception)
async def _unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Catch-all handler for unexpected exceptions (HTTP 500).

    Logs the full exception server-side for diagnosis, but returns only a
    safe generic message to the client.  Never exposes tracebacks, internal
    paths, database details, or provider information in the response.
    """
    req_id = request_id_var.get()
    logger.exception(
        "Unexpected error on %s %s",
        request.method,
        request.url.path,
        extra={"request_id": req_id},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "request_id": req_id},
    )


# Middleware registration order: each add_middleware call wraps the previous
# stack.  The last-registered middleware is the outermost (first to see the
# request, last to touch the response).
#
# Effective request order:
#   CORS → RequestID → BodySizeLimit → SecurityHeaders → app
# Effective response order:
#   app → SecurityHeaders → BodySizeLimit → RequestID → CORS
app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_BodySizeLimitMiddleware)
app.add_middleware(_RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(clients_router)
app.include_router(cases_router)
app.include_router(documents_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(agent_router)
app.include_router(timeline_router)
