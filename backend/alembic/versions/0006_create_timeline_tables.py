"""create timeline_events and timeline_contradictions tables

Revision ID: 0006_create_timeline_tables
Revises: 0005_create_conversations
Create Date: 2026-10-17

Changes
-------
1. `timeline_events`        — AI-extracted events from case documents.
2. `timeline_contradictions` — potential discrepancies detected between
                               statements in case documents.

Design decisions
----------------
case_id FK → cases (CASCADE)
    Deleting a case removes all derived analysis records.  Analysis is
    entirely derived from case documents; no independent value after
    case deletion.

source_document_id / source_chunk_id FKs (SET NULL)
    Deleting a document preserves events for review but NULLs the
    source reference.  This is intentional: an event may have been
    reviewed and marked as significant before its source document is
    removed.

people / organizations columns
    JSON-encoded TEXT lists.  SQLite-compatible and avoids a junction
    table for what is currently read-only, non-queried data.

source_quote VARCHAR(500)
    Short verified excerpt from the source chunk.  Never stores full
    document text.

extraction_confidence / confidence FLOAT
    Model-estimated confidence in [0.0, 1.0].  NOT a calibrated
    probability; labelled clearly in API responses.

review_status VARCHAR(20)
    Workflow field: UNREVIEWED | REVIEWED | DISPUTED.

Indexes
-------
    - timeline_events.case_id (queries for all events in a case)
    - timeline_events.event_date (chronological ordering)
    - timeline_events.(case_id, event_date) — composite for sorted case queries
    - timeline_events.source_document_id (find events by document)
    - timeline_contradictions.case_id

downgrade
    Drops both tables in reverse dependency order.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_create_timeline_tables"
down_revision: str | None = "0005_create_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # timeline_events                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "timeline_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False, server_default="OTHER"),
        sa.Column("event_date", sa.Date, nullable=True),
        sa.Column("event_date_end", sa.Date, nullable=True),
        sa.Column(
            "date_precision", sa.String(20), nullable=False, server_default="UNKNOWN"
        ),
        # JSON-encoded list of person names
        sa.Column("people", sa.Text, nullable=False, server_default="[]"),
        # JSON-encoded list of organization names
        sa.Column("organizations", sa.Text, nullable=False, server_default="[]"),
        sa.Column("source_quote", sa.String(500), nullable=True),
        sa.Column("source_page", sa.Integer, nullable=True),
        sa.Column("extraction_confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column(
            "review_status", sa.String(20), nullable=False, server_default="UNREVIEWED"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_timeline_events_case_id", "timeline_events", ["case_id"])
    op.create_index("ix_timeline_events_event_date", "timeline_events", ["event_date"])
    op.create_index(
        "ix_timeline_events_case_date", "timeline_events", ["case_id", "event_date"]
    )
    op.create_index(
        "ix_timeline_events_source_document_id",
        "timeline_events",
        ["source_document_id"],
    )

    # ------------------------------------------------------------------ #
    # timeline_contradictions                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "timeline_contradictions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False, server_default="OTHER"),
        sa.Column("severity", sa.String(20), nullable=False, server_default="MEDIUM"),
        sa.Column("summary", sa.String(500), nullable=False),
        # Statement A
        sa.Column("statement_a", sa.Text, nullable=False),
        sa.Column(
            "source_document_a_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_chunk_a_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_quote_a", sa.String(500), nullable=False),
        # Statement B
        sa.Column("statement_b", sa.Text, nullable=False),
        sa.Column(
            "source_document_b_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_chunk_b_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_quote_b", sa.String(500), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column(
            "review_status", sa.String(20), nullable=False, server_default="UNREVIEWED"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_timeline_contradictions_case_id",
        "timeline_contradictions",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_timeline_contradictions_case_id", table_name="timeline_contradictions")
    op.drop_table("timeline_contradictions")

    op.drop_index("ix_timeline_events_source_document_id", table_name="timeline_events")
    op.drop_index("ix_timeline_events_case_date", table_name="timeline_events")
    op.drop_index("ix_timeline_events_event_date", table_name="timeline_events")
    op.drop_index("ix_timeline_events_case_id", table_name="timeline_events")
    op.drop_table("timeline_events")
