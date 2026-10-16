"""
Health and readiness endpoints — Day 9.

Endpoint summary
----------------
GET /health           — Legacy combined endpoint (backwards-compatible).
                        Returns {"status": "ok", "version": "...", "database": "ok|unavailable"}.
                        Always HTTP 200, even when the database is unavailable.

GET /health/live      — Liveness probe.
                        Confirms the application process is running and the
                        ASGI server is accepting connections.
                        Always HTTP 200 when reachable.
                        Does NOT check external dependencies.

GET /health/ready     — Readiness probe.
                        Checks all dependencies required to serve requests:
                          - Database connectivity (bounded by db_health_check_timeout_seconds)
                        HTTP 200 when all checks pass; HTTP 503 when any check fails.
                        Use this endpoint to gate deployment roll-outs and load-balancer
                        traffic routing.

GET /health/config    — Provider configuration status.
                        Reports whether required AI provider configuration is present.
                        Does NOT make any network calls to LLM or embedding APIs.
                        Always HTTP 200 (the endpoint is informational, not a gate).

Security notes
--------------
  - None of these endpoints expose connection strings, credentials, internal
    paths, stack traces, or detailed diagnostic information.
  - The /health/config endpoint reports only whether keys are set (boolean),
    not key values or key prefixes.
  - In production, consider protecting /health/ready and /health/config behind
    a network-level restriction (e.g., only reachable from the load balancer
    or an internal network).
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.db.session import check_db_connection, check_db_ready

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Legacy health response — backwards-compatible with Day 1–8 shape."""

    status: str
    version: str
    database: str


class LivenessResponse(BaseModel):
    status: str  # always "ok"


class ReadinessCheck(BaseModel):
    database: str  # "ok" | "unavailable" | "timeout"


class ReadinessResponse(BaseModel):
    status: str  # "ok" | "degraded"
    checks: ReadinessCheck


class ProviderStatus(BaseModel):
    llm: str  # "configured" | "not_configured"
    embedding: str  # "local" | "not_configured"


class ConfigStatusResponse(BaseModel):
    status: str  # always "ok"
    environment: str
    providers: ProviderStatus


# ---------------------------------------------------------------------------
# GET /health  (legacy — keep for backwards compatibility)
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """
    Legacy health check.  Always HTTP 200.

    Returns "database": "unavailable" when the database cannot be reached,
    but does NOT change the HTTP status code.  Use /health/ready for a
    probe that gates traffic on database availability.
    """
    db_ok = check_db_connection()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        database="ok" if db_ok else "unavailable",
    )


# ---------------------------------------------------------------------------
# GET /health/live
# ---------------------------------------------------------------------------


@router.get("/health/live", response_model=LivenessResponse, tags=["health"])
def liveness() -> LivenessResponse:
    """
    Liveness probe.

    Confirms that the application process is running and the HTTP server
    is accepting connections.  Always returns HTTP 200.

    This endpoint intentionally does NOT check any external dependencies
    (database, LLM, embeddings).  A failed liveness check means the
    process itself is broken and should be restarted.  External dependency
    failures are reported by /health/ready.
    """
    return LivenessResponse(status="ok")


# ---------------------------------------------------------------------------
# GET /health/ready
# ---------------------------------------------------------------------------


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    tags=["health"],
    responses={503: {"model": ReadinessResponse}},
)
def readiness(response_obj: None = None) -> ReadinessResponse:
    """
    Readiness probe.

    Checks all dependencies required to serve API requests:
      - Database: a SELECT 1 query with a bounded timeout.

    HTTP 200 when all checks pass.
    HTTP 503 when any check fails — the application should not receive
    traffic until it returns to a healthy state.

    Note: embedding model loading and LLM provider connectivity are NOT
    checked here.  Model loading is deferred to first use.  LLM
    availability is reported by /health/config (informational only).
    """
    from fastapi.responses import JSONResponse

    db_status, db_healthy = _check_database()

    all_healthy = db_healthy

    resp = ReadinessResponse(
        status="ok" if all_healthy else "degraded",
        checks=ReadinessCheck(database=db_status),
    )

    if not all_healthy:
        return JSONResponse(status_code=503, content=resp.model_dump())  # type: ignore[return-value]
    return resp


# ---------------------------------------------------------------------------
# GET /health/config
# ---------------------------------------------------------------------------


@router.get("/health/config", response_model=ConfigStatusResponse, tags=["health"])
def config_status() -> ConfigStatusResponse:
    """
    Provider configuration status.

    Reports whether required AI providers are configured, without making
    any network calls.  Always returns HTTP 200.

    Use this endpoint during local development to verify that environment
    variables are set correctly before testing AI features.
    """
    llm_configured = bool(settings.llm_api_key) and settings.llm_provider != "none"
    embedding_provider = "local"  # sentence-transformers runs locally

    return ConfigStatusResponse(
        status="ok",
        environment=settings.environment,
        providers=ProviderStatus(
            llm="configured" if llm_configured else "not_configured",
            embedding=embedding_provider,
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_database() -> tuple[str, bool]:
    """
    Run the database health check with a bounded timeout.

    Returns:
        (status_string, is_healthy)
        status_string: "ok" | "unavailable" | "timeout"
    """
    try:
        ok = check_db_ready()
        if ok:
            return ("ok", True)
        return ("unavailable", False)
    except Exception:
        logger.warning("Database readiness check raised an unexpected exception")
        return ("unavailable", False)
