import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class CaseStatus(str, PyEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class Case(Base):
    """
    A legal case belonging to a Client.

    Access is controlled by CaseMembership:
    - ADMIN can access any case.
    - Non-admin users can only access cases where they hold a CaseMembership.

    This is enforced at the database query level, never post-fetch.
    """

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("clients.id"),
        nullable=False,
        index=True,
    )
    case_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CaseStatus.OPEN
    )
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

    client: Mapped["Client"] = relationship("Client", back_populates="cases")  # noqa: F821
    memberships: Mapped[list["CaseMembership"]] = relationship(  # noqa: F821
        "CaseMembership",
        back_populates="case",
        cascade="all, delete-orphan",
    )
