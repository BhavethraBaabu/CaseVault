import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserRole(str, PyEnum):
    """
    User roles controlling system access.

    ADMIN           — full system access
    LAWYER          — normal authenticated access
    RESTRICTED_LAWYER — authenticated but intentionally limited scope
                        (case/document-level restrictions enforced in Day 3+)
    """

    ADMIN = "ADMIN"
    LAWYER = "LAWYER"
    RESTRICTED_LAWYER = "RESTRICTED_LAWYER"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default=UserRole.LAWYER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
