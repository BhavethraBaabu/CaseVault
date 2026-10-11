import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    """
    Document metadata returned to clients.

    storage_key is intentionally excluded — internal filesystem paths
    must never be exposed in API responses.
    """

    id: uuid.UUID
    case_id: uuid.UUID
    uploaded_by: uuid.UUID | None
    original_filename: str
    content_type: str
    file_size: int
    file_hash: str
    status: DocumentStatus
    page_count: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentChunkResponse(BaseModel):
    """A single text chunk extracted from a document."""

    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    token_count: int | None
    page_number: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
