"""
Search request and response schemas for Day 5 semantic search.

No embedding vectors are included in responses.
No storage paths or internal keys are exposed.
"""

import uuid

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    """
    Semantic search request.

    query    — The natural-language search text (1–2000 chars).
    case_id  — Optional UUID.  If supplied, restricts results to that case.
               The backend verifies case access independently; a forged
               case_id will produce an error, not leaked results.
    limit    — Maximum results to return (1–50, default 10).
    """

    query: str = Field(..., min_length=1, max_length=2000)
    case_id: uuid.UUID | None = None
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank or whitespace-only.")
        return v.strip()


class SearchResultItem(BaseModel):
    """A single ranked result from a semantic search."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    case_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    content: str
    # Cosine similarity in [0, 1].  Higher means more similar to the query.
    # Computed as 1 − cosine_distance (pgvector <=> operator in production).
    similarity: float


class SearchResponse(BaseModel):
    """Semantic search response."""

    query: str
    results: list[SearchResultItem]
    total: int
