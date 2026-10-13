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
"""

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
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
from app.core.config import settings

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
    yield


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

# Middleware registration order: each add_middleware call wraps the previous
# stack.  The last-registered middleware is the outermost (first to see the
# request, last to touch the response).
#
# Effective request order:  CORS → BodySizeLimit → SecurityHeaders → app
# Effective response order: app → SecurityHeaders → BodySizeLimit → CORS
app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(_BodySizeLimitMiddleware)
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
