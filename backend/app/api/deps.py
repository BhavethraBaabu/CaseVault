"""
FastAPI dependency injection.

Authentication and authorization dependencies used across all protected routes.

Security model:
  REQUEST
    → Authentication  (who are you?)       — get_current_user
    → Authorization   (can you access this?) — require_role / get_authorized_case
                                              / require_case_role
    → Database query  (scoped to authorized set)

CRITICAL: Do NOT query first and filter unauthorized records afterward.
          Authorization must be encoded in the database query.

Role distinction:
  System roles (UserRole):   ADMIN / LAWYER / RESTRICTED_LAWYER
    → Control what a user can do globally across the system.
  Case roles (CaseMemberRole): OWNER / MEMBER / VIEWER
    → Control what a user can do within a specific case.
  These are independent concepts. System role LAWYER does not imply
  any particular case role; case access is always checked via CaseMembership.

Resource-hiding strategy:
  Unauthorized access to a specific resource returns HTTP 404 (not 403).
  This avoids revealing whether the resource exists to unauthorized users.
  Exception: explicit system-role violations (e.g., RESTRICTED_LAWYER creating
  a case) return 403 because the issue is the user's global role, not the resource.
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
from app.models.case import Case
from app.models.case_membership import CaseMemberRole, CaseMembership
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
      4. Load user from database
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
    Return a dependency that enforces one of the given system roles.

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


def get_authorized_case(
    case_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Case:
    """
    Dependency: return the case if the current user can access it.

    Authorization is enforced at query time:
    - ADMIN: unrestricted access to any case
    - Others: must hold a CaseMembership for this case (any role)

    Returns HTTP 404 for non-members to hide resource existence.
    """
    if current_user.role == UserRole.ADMIN:
        case = db.get(Case, case_id)
    else:
        case = (
            db.query(Case)
            .join(CaseMembership, CaseMembership.case_id == Case.id)
            .filter(Case.id == case_id, CaseMembership.user_id == current_user.id)
            .first()
        )
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )
    return case


def require_case_role(*roles: CaseMemberRole):
    """
    Factory: return a dependency that verifies the user's case-level role.

    ADMIN bypasses the check (global access).
    Non-admin users must:
      1. Hold a CaseMembership for the case (otherwise HTTP 404).
      2. Have one of the specified roles (otherwise HTTP 403).

    Usage:
        OwnerOrMember = Depends(require_case_role(CaseMemberRole.OWNER, CaseMemberRole.MEMBER))
    """

    def _check(
        case_id: uuid.UUID,
        db: Annotated[Session, Depends(get_db)],
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> Case:
        if current_user.role == UserRole.ADMIN:
            case = db.get(Case, case_id)
            if case is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found",
                )
            return case

        membership = (
            db.query(CaseMembership)
            .filter(
                CaseMembership.case_id == case_id,
                CaseMembership.user_id == current_user.id,
            )
            .first()
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Case not found",
            )
        if membership.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient case permissions",
            )
        case = db.get(Case, case_id)
        return case

    return _check
