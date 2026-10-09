"""
Shared test utilities for Day 3 tests.

Provides fast helpers for creating users, clients, cases, and memberships
without going through the HTTP layer (direct DB writes for speed).
"""
import uuid

from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models.case import Case, CaseStatus
from app.models.case_membership import CaseMemberRole, CaseMembership
from app.models.client import Client
from app.models.user import User, UserRole


def make_user(
    db: Session,
    email: str | None = None,
    role: UserRole = UserRole.LAWYER,
    full_name: str = "Test User",
) -> User:
    """Create and persist a user with the given role."""
    if email is None:
        email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        password_hash=hash_password("TestPass123!"),
        full_name=full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    """Return Authorization headers for the given user."""
    token = create_access_token(subject=str(user.id), role=user.role)
    return {"Authorization": f"Bearer {token}"}


def make_client(
    db: Session,
    name: str = "Test Client",
    email: str | None = None,
) -> Client:
    """Create and persist a client."""
    client = Client(name=name, email=email)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def make_case(
    db: Session,
    client: Client,
    case_number: str | None = None,
    title: str = "Test Case",
    status: CaseStatus = CaseStatus.OPEN,
) -> Case:
    """Create and persist a case (no membership created)."""
    if case_number is None:
        case_number = f"CASE-{uuid.uuid4().hex[:6].upper()}"
    case = Case(
        client_id=client.id,
        case_number=case_number,
        title=title,
        status=status,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def add_membership(
    db: Session,
    case: Case,
    user: User,
    role: CaseMemberRole = CaseMemberRole.MEMBER,
) -> CaseMembership:
    """Create a CaseMembership for the given user and case."""
    membership = CaseMembership(
        case_id=case.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership
