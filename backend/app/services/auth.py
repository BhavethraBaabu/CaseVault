"""
Authentication service layer.

Business logic lives here, not in route handlers.
"""
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.auth import RegisterRequest


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, req: RegisterRequest) -> User:
    """
    Create and persist a new user with a hashed password.
    Default role is LAWYER. Admins are provisioned separately.
    """
    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        role=UserRole.LAWYER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """
    Return the user if credentials are valid, None otherwise.
    Uses constant-time comparison via passlib to resist timing attacks.
    """
    user = get_user_by_email(db, email)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
