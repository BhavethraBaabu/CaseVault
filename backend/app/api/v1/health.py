from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.db.session import check_db_connection

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    """
    Return application health status including database connectivity.
    """
    db_ok = check_db_connection()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        database="ok" if db_ok else "unavailable",
    )
