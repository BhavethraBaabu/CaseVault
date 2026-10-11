"""create conversations and conversation_messages tables

Revision ID: 0005_create_conversations
Revises: 0004_add_embeddings
Create Date: 2026-10-11

Changes
-------
1. `conversations`         — one row per chat session (owned by a user).
2. `conversation_messages` — individual turns (user/assistant) within a conversation.

Design decisions
----------------
case_id (nullable, no FK)
    Conversations may be optionally scoped to a single case.  We store
    the UUID without a foreign key so that deleting a case does not
    cascade-delete the conversation record.  The application re-verifies
    case membership on every /chat/ask call regardless.

No FK from case_id → cases
    This is intentional: deleting a case should not silently remove
    conversation history.  The application layer handles the access check.

message.role: varchar(20)
    Values: "user" | "assistant".  Kept as a plain string rather than
    an enum to simplify migrations if new roles are ever added.

Indexes
    - conversations.user_id    — fast lookup of a user's conversations
    - conversations.case_id    — optional; useful for case-scoped queries
    - conversation_messages.conversation_id — required for message loading

downgrade
    Drops both tables in reverse dependency order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_create_conversations"
down_revision: str | None = "0004_add_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("title", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_case_id", "conversations", ["case_id"])

    op.create_table(
        "conversation_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_messages_conversation_id",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")

    op.drop_index("ix_conversations_case_id", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
