"""create clients, cases, and case_memberships tables

Revision ID: 0002_create_clients_cases
Revises: 0001_create_users
Create Date: 2026-10-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_create_clients_cases"
down_revision: str | None = "0001_create_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # clients
    # ------------------------------------------------------------------
    op.create_table(
        "clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("organization", sa.String(255), nullable=True),
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
    op.create_index("ix_clients_name", "clients", ["name"])

    # ------------------------------------------------------------------
    # cases
    # ------------------------------------------------------------------
    op.create_table(
        "cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id"),
            nullable=False,
        ),
        sa.Column("case_number", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="OPEN",
        ),
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
    op.create_index("ix_cases_client_id", "cases", ["client_id"])
    op.create_index("ix_cases_case_number", "cases", ["case_number"], unique=True)

    # ------------------------------------------------------------------
    # case_memberships
    # ------------------------------------------------------------------
    op.create_table(
        "case_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default="MEMBER",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_case_memberships_case_id", "case_memberships", ["case_id"])
    op.create_index("ix_case_memberships_user_id", "case_memberships", ["user_id"])
    op.create_unique_constraint(
        "uq_case_membership", "case_memberships", ["case_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_case_membership", "case_memberships", type_="unique")
    op.drop_index("ix_case_memberships_user_id", table_name="case_memberships")
    op.drop_index("ix_case_memberships_case_id", table_name="case_memberships")
    op.drop_table("case_memberships")

    op.drop_index("ix_cases_case_number", table_name="cases")
    op.drop_index("ix_cases_client_id", table_name="cases")
    op.drop_table("cases")

    op.drop_index("ix_clients_name", table_name="clients")
    op.drop_table("clients")
