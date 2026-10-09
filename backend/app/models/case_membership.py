import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class CaseMemberRole(str, PyEnum):
    """
    Case-level membership role.

    IMPORTANT: This is distinct from the system-level UserRole
    (ADMIN / LAWYER / RESTRICTED_LAWYER).

    System role controls what a user can do globally.
    Case role controls what a user can do within a specific case.

    OWNER  — view, edit, and manage case members
    MEMBER — view and edit
    VIEWER — view only; cannot edit or manage members
    """

    OWNER = "OWNER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class CaseMembership(Base):
    """
    Associates a User with a Case at a specific CaseMemberRole.

    The unique constraint on (case_id, user_id) prevents duplicate memberships.
    This table is the primary authorization boundary for case-level access:
    a user must have a record here to access a case (unless they are ADMIN).
    """

    __tablename__ = "case_memberships"
    __table_args__ = (
        UniqueConstraint("case_id", "user_id", name="uq_case_membership"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("cases.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CaseMemberRole.MEMBER
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    case: Mapped["Case"] = relationship("Case", back_populates="memberships")  # noqa: F821
    user: Mapped["User"] = relationship("User")  # noqa: F821
