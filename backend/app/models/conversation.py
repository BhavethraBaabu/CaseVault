"""
Conversation and message persistence for the Day 6 RAG chat feature.

Authorization model
-------------------
  - A conversation is always owned by the user who created it.
  - Only the owner (or ADMIN) may read or continue it.
  - Case-scoped conversations re-verify case membership on every message.
  - Conversation history is NOT a source of authorization.  Access rights
    are re-evaluated from the database on every /chat/ask call.

Security notes
--------------
  - user_id is always set from the authenticated token, never from the
    request body.
  - Conversations cannot be accessed by guessing UUIDs — the owner check
    is enforced in the API layer.
  - Message content is NOT logged at INFO level to avoid leaking
    confidential document excerpts.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Conversation(Base):
    """
    A persistent chat conversation owned by a user.

    A conversation may optionally be scoped to a single case.  When
    case_id is set, all questions in this conversation are restricted to
    that case's documents (re-verified on each /chat/ask call).

    Cascades: deleting a Conversation removes all its messages.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional case scope.  If set, all retrieval is restricted to this case.
    # Stored as a plain UUID (no FK) so conversations survive case deletion
    # gracefully — messages become orphaned but the record is not lost.
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True), nullable=True, index=True
    )
    # Short title derived from the first user question (truncated to 120 chars).
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
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

    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    """
    A single message in a conversation.

    role: "user" for the human question, "assistant" for the AI answer.

    Message content may contain confidential document excerpts; do not
    log at INFO level.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
