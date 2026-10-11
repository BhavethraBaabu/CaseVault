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
