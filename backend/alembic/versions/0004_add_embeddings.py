"""add embedding columns to document_chunks

Revision ID: 0004_add_embeddings
Revises: 0003_create_documents_chunks
Create Date: 2026-10-11

Changes
-------
1. Enable the pgvector extension (CREATE EXTENSION IF NOT EXISTS vector).
2. Add `embedding`         vector(384)     NULL — the embedding vector.
3. Add `embedding_model`   varchar(100)    NULL — model that produced it.
4. Add `embedding_status`  varchar(20) NOT NULL DEFAULT 'PENDING'.
5. Create an HNSW index on `embedding` using cosine distance.

Design decisions
----------------
embedding dimension
    384 — fixed for sentence-transformers/all-MiniLM-L6-v2.  If the model
    changes, a new migration must ALTER the column and re-embed all chunks.

nullable embedding
    Existing chunks have no embedding; NULL means "not yet generated".
    The pipeline processes PENDING/FAILED chunks in batches.

Index choice: HNSW with cosine distance
    HNSW (Hierarchical Navigable Small World) provides fast approximate
    nearest-neighbour search with good recall at the cost of higher build
    time and memory versus IVFFlat.  For a small demo dataset, exact search
    (sequential scan) is equally fast; the index pays off at scale.

    Operator class: vector_cosine_ops → enables the <=> (cosine distance)
    operator.  The search query MUST use the same metric; mixing cosine
    distance index with L2 distance queries would produce wrong rankings.

    m=16, ef_construction=64 are pgvector defaults, balanced for moderate
    dataset sizes.

exact vs approximate search trade-off
    For ≤ 10 000 chunks the sequential scan is fast enough (~10 ms on a
    modern CPU).  The HNSW index reduces query time to ~1 ms at scale but
    uses additional RAM (~3 MB per 10 000 chunks at dim=384).

    The index is optional; dropping it reverts to exact search automatically.

downgrade
    Drops the HNSW index first (index depends on the column), then the
    three new columns.  The pgvector extension is NOT dropped on downgrade
    because other tables might use it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_add_embeddings"
down_revision: str | None = "0003_create_documents_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enable pgvector extension
    # IF NOT EXISTS ensures idempotency across repeated runs.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add embedding column: vector(384), nullable
    # Using raw SQL because op.add_column does not know about the pgvector
    # dialect type in all Alembic environments.
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector(384)"
    )

    # 3. Add embedding_model column
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(100), nullable=True),
    )

    # 4. Add embedding_status column with default PENDING
    op.add_column(
        "document_chunks",
        sa.Column(
            "embedding_status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
        ),
    )

    # 5. HNSW index for cosine distance search
    # The operator class vector_cosine_ops is REQUIRED for <=> queries.
    # Mixing this index with L2 (<->) or inner-product (<#>) queries would
    # yield incorrect results because pgvector uses different index structures.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    # Drop the HNSW index first (index references the column)
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")

    # Drop the three new columns
    op.drop_column("document_chunks", "embedding_status")
    op.drop_column("document_chunks", "embedding_model")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")

    # NOTE: pgvector extension is NOT dropped on downgrade.
    # Removing the extension could break other tables or indexes that depend
    # on it.  Remove manually if absolutely required.
