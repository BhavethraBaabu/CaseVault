"""
Chat and RAG request/response schemas — Day 6.

No embedding vectors, storage paths, or internal keys are exposed.
Source citations reference only data from the authorized retrieval set.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    """
    RAG question-answering request.

    question        — natural-language question (1–2000 chars, non-blank).
    conversation_id — UUID of an existing conversation to continue, or null
                      to start a new one.  The backend verifies ownership;
                      a foreign UUID will return an error, not leaked history.
    case_id         — optional case scope UUID.  Backend re-verifies access;
                      specifying an unauthorized case returns an error.
    """

    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank or whitespace-only.")
        return v.strip()


class SourceCitation(BaseModel):
    """
    A validated source citation returned with an AI answer.

    Sources come exclusively from the authorized retrieval set.
    They are validated application-side; the model cannot inject
    arbitrary document references.

    verification_status:
      "verified"   — source resolves AND any quoted passage detected in the
                     answer appears verbatim in the stored chunk text.
      "unverified" — source resolves but no exact quotation was detected
                     near the citation marker.
      "invalid"    — source resolves but a detected quoted passage does NOT
                     appear in the stored chunk text (possible misquote).

    Note: "verified" confirms the source reference and quotation match.  It
    does NOT certify that the AI's broader claim is legally correct.
    """

    document_id: uuid.UUID
    document_name: str
    case_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    excerpt: str
    # Cosine similarity ∈ [0, 1] from the retrieval step.
    similarity: float
    # Citation verification
    verification_status: str  # "verified" | "unverified" | "invalid"
    verification_note: str
    quoted_text: str | None


class AskResponse(BaseModel):
    """
    RAG answer with conversation ID and validated citations.

    insufficient_evidence: True when no relevant authorized chunks were
    found or the model explicitly indicated insufficient evidence.

    answer: Never fabricated — based only on retrieved evidence.

    sources: Validated citations only.  May be empty if no [SOURCE:N]
    references appear in the answer.

    DISCLAIMER: Answers are AI-generated and may be incorrect.  Always
    verify claims against the cited source documents.
    """

    conversation_id: uuid.UUID
    answer: str
    insufficient_evidence: bool
    sources: list[SourceCitation]


class SourceDetailResponse(BaseModel):
    """
    Full source detail for a cited document chunk.

    Returned by GET /chat/sources/{chunk_id}.  The chunk is re-fetched
    from the database and re-authorized on every request, so this response
    reflects the current state of the stored source.

    If quoted_text was supplied as a query parameter, verification_status
    reflects whether that text appears verbatim in the stored content.
    If no quoted_text was supplied, verification_status is "unverified".
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    case_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    content: str  # Full stored chunk text
    verification_status: str  # "verified" | "unverified" | "invalid"
    verification_note: str
    quoted_text: str | None  # The text that was verified, if any


class ConversationResponse(BaseModel):
    """Summary of a conversation for listing."""

    id: uuid.UUID
    case_id: uuid.UUID | None
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """A single message in a conversation."""

    id: uuid.UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
