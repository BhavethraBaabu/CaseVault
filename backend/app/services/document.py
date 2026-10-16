"""
Document processing orchestration service.

Coordinates the full ingestion pipeline:
    Upload → Validate → Store → Extract → Normalize → Chunk → Persist

Authorization is NOT enforced here — that is the responsibility of the API
layer (see api/v1/documents.py).

Processing is synchronous on Day 4. This means the HTTP request blocks until
extraction and chunking complete. For documents near the 10 MB limit, this
may take several seconds. A background-job queue is a natural Day 5+ improvement.

Known limitation:
    Synchronous processing ties up a worker thread for the duration of the
    request. Consider Celery, ARQ, or FastAPI BackgroundTasks for production.
"""

import hashlib
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.request_context import get_request_id
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.services.chunking import chunk_pages
from app.services.extraction import ExtractionError, extract_text
from app.services.file_validation import sanitize_filename, validate_file
from app.services.storage import StorageError, get_storage

logger = logging.getLogger(__name__)


class DocumentProcessingError(Exception):
    """Raised for unrecoverable processing failures after file is stored."""


def ingest_document(
    db: Session,
    case_id: uuid.UUID,
    uploaded_by_id: uuid.UUID,
    filename: str,
    content: bytes,
) -> Document:
    """
    Ingest a document: validate, store, extract, chunk, and persist.

    Validation errors (bad type/size/content) raise FileValidationError
    before any database records or files are created.

    If storage or extraction fails after the database record is created,
    the document is marked FAILED and the partial state is cleaned up.

    Args:
        db:             SQLAlchemy session.
        case_id:        ID of the case this document belongs to.
        uploaded_by_id: ID of the user uploading the document.
        filename:       Original filename from the upload (used for display only).
        content:        Raw file bytes.

    Returns:
        Persisted Document instance (status READY on success, FAILED on error).

    Raises:
        FileValidationError if content fails validation (no records created).
    """
    _t_start = time.perf_counter()

    # --- 1. Validate (raises FileValidationError on failure) ---
    safe_filename = sanitize_filename(filename)
    content_type = validate_file(filename, content, max_size=settings.max_upload_size_bytes)

    # --- 2. Compute checksum ---
    file_hash = hashlib.sha256(content).hexdigest()

    # --- 3. Generate server-controlled storage key ---
    storage_key = f"{case_id}/{uuid.uuid4()}"

    # --- 4. Create document record (status=PROCESSING) ---
    doc = Document(
        case_id=case_id,
        uploaded_by=uploaded_by_id,
        original_filename=safe_filename,
        storage_key=storage_key,
        content_type=content_type,
        file_size=len(content),
        file_hash=file_hash,
        status=DocumentStatus.PROCESSING,
    )
    db.add(doc)
    db.flush()  # Assign doc.id without committing
    doc_id = doc.id

    # --- 5. Persist file to storage ---
    storage = get_storage()
    try:
        storage.save(storage_key, content)
    except Exception as exc:
        db.rollback()
        raise DocumentProcessingError("Failed to store file. Please try again.") from exc

    # --- 6. Extract, chunk, and save (best-effort; failure → FAILED status) ---
    try:
        result = extract_text(content, content_type)
        chunks = chunk_pages(
            result.pages,
            chunk_size_words=settings.chunk_size_words,
            chunk_overlap_words=settings.chunk_overlap_words,
        )

        # Save chunks
        for chunk in chunks:
            db.add(
                DocumentChunk(
                    document_id=doc_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                )
            )

        doc.status = DocumentStatus.READY
        doc.page_count = result.page_count
        doc.error_message = None
        db.commit()

        _t_total = (time.perf_counter() - _t_start) * 1000
        logger.info(
            "document.ingest completed",
            extra={
                "operation": "document.ingest",
                "duration_ms": round(_t_total, 1),
                "content_type": content_type,
                "file_size_bytes": len(content),
                "page_count": result.page_count,
                "chunk_count": len(chunks),
                "status": "ready",
                "request_id": get_request_id(),
            },
        )

    except ExtractionError as exc:
        _t_total = (time.perf_counter() - _t_start) * 1000
        logger.warning(
            "document.ingest extraction failed",
            extra={
                "operation": "document.ingest",
                "duration_ms": round(_t_total, 1),
                "content_type": content_type,
                "file_size_bytes": len(content),
                "status": "failed",
                "error_category": "extraction",
                "request_id": get_request_id(),
            },
        )
        _mark_failed(db, doc, str(exc))
    except Exception:
        # Catch-all: log internally but return a safe generic message
        _t_total = (time.perf_counter() - _t_start) * 1000
        logger.error(
            "document.ingest unexpected failure",
            extra={
                "operation": "document.ingest",
                "duration_ms": round(_t_total, 1),
                "content_type": content_type,
                "file_size_bytes": len(content),
                "status": "failed",
                "error_category": "unexpected",
                "request_id": get_request_id(),
            },
        )
        _mark_failed(
            db,
            doc,
            "Document processing failed. The file was stored but could not be processed.",
        )

    db.refresh(doc)
    return doc


def _mark_failed(db: Session, doc: Document, error_message: str) -> None:
    """Mark a document as FAILED with a safe error message."""
    try:
        db.rollback()
        doc.status = DocumentStatus.FAILED
        doc.error_message = error_message[:1000]
        doc.updated_at = datetime.now(UTC)
        db.add(doc)
        db.commit()
    except Exception:
        # If we can't even persist the FAILED status, the DB may be unavailable.
        # Do not raise; the caller will receive the partially-failed state.
        pass


def get_document(db: Session, document_id: uuid.UUID) -> Document | None:
    """Return a document by ID or None if not found."""
    return db.get(Document, document_id)


def list_documents_for_case(db: Session, case_id: uuid.UUID) -> list[Document]:
    """
    Return all documents for a case, ordered by creation time.

    Authorization must be verified by the caller before calling this function.
    """
    return (
        db.query(Document)
        .filter(Document.case_id == case_id)
        .order_by(Document.created_at.desc())
        .all()
    )


def get_document_chunks(db: Session, document_id: uuid.UUID) -> list[DocumentChunk]:
    """Return chunks for a document in order."""
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )


def delete_document(db: Session, doc: Document) -> None:
    """
    Delete a document, its chunks, and its stored file.

    Chunks are deleted via SQLAlchemy cascade (Document.chunks relationship).
    The storage file is deleted after the database commit; if the file is
    missing on disk, the deletion proceeds without error (idempotent).

    If storage deletion fails (e.g. permissions), the error is logged but
    does not roll back the database deletion.
    """
    storage_key = doc.storage_key
    db.delete(doc)
    db.commit()

    # Best-effort file deletion — do not crash if file is missing
    try:
        get_storage().delete(storage_key)
    except StorageError:
        pass  # File already gone; that is acceptable
    except Exception:
        pass  # Log in production; do not surface to client
