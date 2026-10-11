import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EmbeddingVector


class DocumentStatus(str, PyEnum):
    """
    Lifecycle status of a document.

    UPLOADED   — file received and stored; processing not yet started
    PROCESSING — text extraction and chunking in progress
    READY      — fully processed; chunks are available
    FAILED     — processing failed; error_message contains a safe description
    """

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class Document(Base):
    """
    A document uploaded to a case.

    Authorization:
      - ADMIN: unrestricted access across all cases.
      - OWNER/MEMBER: may upload, view, and download.
      - OWNER: may also delete.
      - VIEWER: may view and download only.
      - Non-members: no access (returns 404 to hide existence).

    Storage:
      - File contents are stored on disk at `storage_key` within the
        configured storage root. storage_key is never derived from
        user-supplied input.
      - `original_filename` is a sanitized display name only; it is
        never used as a filesystem path.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,  # SET NULL if uploader is deleted
        index=True,
    )
    # Sanitized display filename — NOT used as a filesystem path
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Server-generated UUID-based key — the only path used for file I/O
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 hex digest of the file content
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentStatus.UPLOADED
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Safe, non-sensitive error description — never includes stack traces or paths
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
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

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )


class EmbeddingStatus(str, PyEnum):
    """
    Lifecycle status of a chunk's embedding.

    PENDING    — chunk exists but has no embedding yet
    PROCESSING — embedding generation in progress (set before batch start)
    READY      — valid embedding stored for current model
    FAILED     — embedding generation failed; safe to retry
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


# Dimension of the all-MiniLM-L6-v2 embedding model (fixed at 384).
# Must match EMBEDDING_DIM in app.core.config.
EMBEDDING_DIMENSION = 384


class DocumentChunk(Base):
    """
    A contiguous, overlapping text chunk extracted from a Document.

    Chunks are ordered by chunk_index (0-based, deterministic).
    token_count is an estimate: words * 1.3, rounded to nearest integer.

    Day 5 adds:
      - embedding: nullable vector(384), populated by the embedding pipeline
      - embedding_model: model name used to generate the embedding
      - embedding_status: tracks embedding lifecycle (PENDING → READY/FAILED)

    The embedding column uses EmbeddingVector, a TypeDecorator that maps to
    vector(384) in PostgreSQL and TEXT (JSON) in SQLite for unit tests.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Estimated token count: len(content.split()) * 1.3, rounded
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Source page (1-indexed) for PDF; None for DOCX/TXT
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # ----- Day 5: Embedding fields -----
    # vector(384) in PostgreSQL, TEXT (JSON array) in SQLite tests.
    # Null until the embedding pipeline runs.
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(EMBEDDING_DIMENSION), nullable=True
    )
    # Name of the model that produced this embedding.
    # Used to detect stale embeddings when the model changes.
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Tracks embedding lifecycle; defaults to PENDING.
    embedding_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EmbeddingStatus.PENDING
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
