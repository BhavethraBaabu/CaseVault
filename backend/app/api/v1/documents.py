"""
Document routes.

POST   /cases/{case_id}/documents              — upload and process a document
GET    /cases/{case_id}/documents              — list documents in a case
GET    /documents/{document_id}                — get document metadata
GET    /documents/{document_id}/download       — download original file
GET    /documents/{document_id}/chunks         — list chunks (authorized)
DELETE /documents/{document_id}               — delete document (OWNER only)

Authorization invariants:
  - Upload:    OWNER or MEMBER (case role); VIEWER and non-members are refused.
  - List/View: any case member (OWNER, MEMBER, VIEWER); non-members get 404.
  - Download:  any case member.
  - Chunks:    any case member.
  - Delete:    OWNER only (case role); ADMIN bypasses.

  ADMIN system role bypasses all case-level checks.
  RESTRICTED_LAWYER can access only cases/documents where they hold a membership.

  Non-members receive HTTP 404 (resource-hiding).
  Role violations receive HTTP 403.

Processing note:
  Document processing is synchronous on Day 4. The upload request blocks
  until extraction and chunking complete. This is a known limitation.

Storage note:
  File paths are never included in API responses.
  Binary download is streamed as bytes; the storage abstraction handles I/O.
"""

import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    get_authorized_case,
    get_authorized_document,
    get_current_user,
    get_db,
    require_case_role,
    require_document_case_role,
)
from app.models.case import Case
from app.models.case_membership import CaseMemberRole
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentChunkResponse, DocumentResponse
from app.services.document import (
    delete_document,
    get_document_chunks,
    ingest_document,
    list_documents_for_case,
)
from app.services.file_validation import FileValidationError
from app.services.storage import StorageError, get_storage

router = APIRouter(tags=["documents"])


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile,
    case: Annotated[
        Case,
        Depends(require_case_role(CaseMemberRole.OWNER, CaseMemberRole.MEMBER)),
    ],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DocumentResponse:
    """
    Upload a document to a case.

    Accepts multipart/form-data with a single 'file' field.
    Supported formats: PDF, DOCX, TXT.
    Maximum size: configured by MAX_UPLOAD_SIZE_BYTES (default 10 MB).

    Processing is synchronous: text extraction and chunking happen during
    this request. The returned document may have status FAILED if extraction
    encountered an error (e.g. scanned PDF with no extractable text).
    """
    content = await file.read()
    filename = file.filename or "unnamed_file"

    try:
        doc = ingest_document(
            db=db,
            case_id=case.id,
            uploaded_by_id=current_user.id,
            filename=filename,
            content=content,
        )
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the document.",
        )

    return DocumentResponse.model_validate(doc)


# ---------------------------------------------------------------------------
# List documents
# ---------------------------------------------------------------------------


@router.get(
    "/cases/{case_id}/documents",
    response_model=list[DocumentResponse],
)
def list_documents(
    case: Annotated[Case, Depends(get_authorized_case)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentResponse]:
    """
    List documents in a case.

    Returns documents for all authorized members (OWNER, MEMBER, VIEWER).
    Documents are ordered by upload date (newest first).
    """
    docs = list_documents_for_case(db, case.id)
    return [DocumentResponse.model_validate(d) for d in docs]


# ---------------------------------------------------------------------------
# Get document metadata
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
)
def get_document_metadata(
    doc: Annotated[Document, Depends(get_authorized_document)],
) -> DocumentResponse:
    """
    Return document metadata.

    Non-members receive 404 (resource-hiding).
    storage_key is never included in the response.
    """
    return DocumentResponse.model_validate(doc)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}/download",
)
def download_document(
    doc: Annotated[Document, Depends(get_authorized_document)],
) -> StreamingResponse:
    """
    Download the original document file.

    Returns the file as an octet-stream with a Content-Disposition header
    using the sanitized original_filename.

    If the physical file is missing (e.g. manual deletion), returns 404.

    Limitation: file is loaded entirely into memory before streaming.
    For production, use streaming from object storage.
    """
    storage = get_storage()
    try:
        content = storage.load(doc.storage_key)
    except StorageError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file is not available.",
        )

    return StreamingResponse(
        io.BytesIO(content),
        media_type=doc.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_filename}"',
            "Content-Length": str(len(content)),
        },
    )


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}/chunks",
    response_model=list[DocumentChunkResponse],
)
def list_chunks(
    doc: Annotated[Document, Depends(get_authorized_document)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentChunkResponse]:
    """
    Return all chunks for a document in order.

    Authorized for any case member (OWNER, MEMBER, VIEWER).
    Returns an empty list if the document has not been processed (status != READY).
    """
    chunks = get_document_chunks(db, doc.id)
    return [DocumentChunkResponse.model_validate(c) for c in chunks]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document_route(
    doc: Annotated[
        Document,
        Depends(require_document_case_role(CaseMemberRole.OWNER)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Delete a document and all its chunks.

    OWNER and ADMIN only.

    The physical file is deleted after the database record. If the file
    is already missing, the deletion proceeds without error.
    """
    delete_document(db, doc)
