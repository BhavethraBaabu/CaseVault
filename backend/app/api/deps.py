"""
FastAPI dependency injection.

Authentication and authorization dependencies used across all protected routes.

Security model:
  REQUEST → Authentication (who are you?) → Authorization (what are you allowed?)
                                                          → Database query

Never reverse this: do NOT query first and filter unauthorized records afterward.
"""
import uuid
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer()


def get_db() -> Generator[Session]:
    """Yield a database session and ensure it is closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Authenticate the request and return the current user.

    Steps:
      1. Read Authorization: Bearer <token> header
      2. Validate JWT signature and expiration
      3. Extract user ID from token subject
      4. Load user from PostgreSQL
      5. Verify user exists
      6. Verify user is active

    Raises HTTP 401 for missing/invalid/expired tokens.
    Raises HTTP 403 for inactive users.

    Role claims in the JWT are informational only — authoritative role
    is always re-read from the database.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return user


def require_role(*roles: UserRole):
    """
    Return a dependency that enforces one of the given roles.

    Usage:
        AdminOnly = Depends(require_role(UserRole.ADMIN))
        LawyerOrAdmin = Depends(require_role(UserRole.ADMIN, UserRole.LAWYER))

    Authentication is always verified first (get_current_user is called internally).
    Authorization — role check — happens before any resource access.
    """

    def _check(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _check
