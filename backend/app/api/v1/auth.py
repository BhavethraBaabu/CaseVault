"""
Authentication routes.

POST /auth/register  — create a new user account
POST /auth/login     — exchange credentials for a JWT
GET  /auth/me        — return the currently authenticated user
POST /auth/logout    — client-side token removal (see note below)
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services.auth import authenticate_user, create_user, get_user_by_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """
    Register a new user. Default role is LAWYER.
    Returns the created user (no password_hash).
    """
    if get_user_by_email(db, req.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )
    return create_user(db, req)


@router.post("/login", response_model=TokenResponse)
def login(
    req: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """
    Authenticate and return a JWT access token.
    Uses a generic error message to avoid leaking whether the email exists.
    """
    user = authenticate_user(db, req.email, req.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the currently authenticated user's profile (no password_hash)."""
    return current_user


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout() -> dict[str, str]:
    """
    Logout endpoint.

    CaseVault uses stateless JWTs. This endpoint does NOT invalidate the token
    server-side — the token remains cryptographically valid until its exp claim.

    The client MUST discard the token locally on logout.

    Production recommendation: implement short-lived access tokens (5–15 min)
    combined with refresh-token rotation, or maintain a server-side token
    revocation list (e.g. Redis blocklist keyed by jti claim).
    """
    return {"message": "Logged out. Please discard your token."}
