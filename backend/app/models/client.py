import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Client(Base):
    """
    A legal client that may have one or more cases.

    Clients are accessed indirectly via Case membership:
    a user can see a client only if they are a member of at least
    one case that belongs to that client.
    ADMIN can see all clients.
    """

    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    cases: Mapped[list["Case"]] = relationship("Case", back_populates="client")  # noqa: F821
