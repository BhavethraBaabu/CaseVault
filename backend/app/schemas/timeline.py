"""
Timeline event and contradiction schemas.

Security notes
--------------
  - No storage paths, embedding vectors, or internal keys are exposed.
  - source_quote fields contain short, verified excerpts only.
  - extraction_confidence and confidence are clearly labelled as model
    estimates, not calibrated probabilities.
  - All results carry an ai_generated flag to remind callers that these
    are AI-extracted values requiring human review.
  - review_status transitions are the only fields modifiable via the API
    (PATCH endpoint).
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.models.timeline import (
    ContradictionCategory,
    ContradictionSeverity,
    DatePrecision,
    EventType,
    ReviewStatus,
)

# ---------------------------------------------------------------------------
# LLM extraction output schemas
# ---------------------------------------------------------------------------
# These are validated against the raw LLM JSON output before any persistence.
# They are NOT exposed directly in API responses.


class _ExtractedEvent(BaseModel):
    """
    Single event as returned by the LLM extraction call.

    Strict validation is intentional: malformed LLM output is rejected
    rather than persisted with incorrect data.
    """

    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=1000)
    event_type: EventType = EventType.OTHER
    # ISO date string "YYYY-MM-DD" or null
    event_date: str | None = None
    event_date_end: str | None = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    people: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    # Must be verified against actual source text before persistence
    source_quote: str = Field(..., min_length=1, max_length=500)
    # Model confidence 0.0–1.0
    extraction_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("event_date", "event_date_end", mode="before")
    @classmethod
    def validate_date_string(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return None
        v = v.strip()
        if not v:
            return None
        # Accept YYYY-MM-DD, YYYY-MM, or YYYY
        import re
        if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", v):
            return v
        return None

    @field_validator("people", "organizations", mode="before")
    @classmethod
    def validate_string_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(item).strip() for item in v if isinstance(item, str) and str(item).strip()][:20]

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        return v.strip()

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        return v.strip()


class _ExtractionResponse(BaseModel):
    """Root of the LLM extraction JSON response."""

    events: list[_ExtractedEvent] = Field(default_factory=list)


class _ExtractedContradiction(BaseModel):
    """
    A potential contradiction as returned by the LLM comparison call.

    Both source_quote_a and source_quote_b must be verified against their
    respective source chunk texts before persistence.
    """

    category: ContradictionCategory = ContradictionCategory.OTHER
    severity: ContradictionSeverity = ContradictionSeverity.MEDIUM
    summary: str = Field(..., min_length=1, max_length=500)
    statement_a: str = Field(..., min_length=1, max_length=2000)
    statement_b: str = Field(..., min_length=1, max_length=2000)
    source_quote_a: str = Field(..., min_length=1, max_length=500)
    source_quote_b: str = Field(..., min_length=1, max_length=500)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    is_contradiction: bool = True

    @field_validator("summary", "statement_a", "statement_b", "source_quote_a", "source_quote_b")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class _ContradictionResponse(BaseModel):
    """Root of the LLM contradiction-detection JSON response."""

    contradictions: list[_ExtractedContradiction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request schemas
# ---------------------------------------------------------------------------


class TimelineAnalyzeRequest(BaseModel):
    """
    Request body for POST /cases/{case_id}/timeline/analyze.

    force_reanalyze  — if True, delete existing events/contradictions and
                       re-run extraction.  Defaults to False so that
                       repeated calls without force do not trigger
                       duplicate work.
    max_documents    — maximum number of READY documents to analyze
                       (default: 5, max: 10).  Bounds per-request LLM cost.
    """

    force_reanalyze: bool = False
    max_documents: int = Field(default=5, ge=1, le=10)


class ContradictionReviewUpdate(BaseModel):
    """PATCH body for updating a contradiction's review_status."""

    review_status: ReviewStatus


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------


class TimelineEventResponse(BaseModel):
    """
    A timeline event as returned by the API.

    All fields are AI-extracted and labelled accordingly.
    source_quote is a short verified excerpt from the source document.
    """

    id: uuid.UUID
    case_id: uuid.UUID
    source_document_id: uuid.UUID | None
    source_document_name: str | None  # Resolved from relationship
    source_chunk_id: uuid.UUID | None
    title: str
    description: str
    event_type: str
    event_date: date | None
    event_date_end: date | None
    date_precision: str
    people: list[str]
    organizations: list[str]
    source_quote: str | None
    source_page: int | None
    # Model estimate — not a calibrated probability.
    extraction_confidence: float
    review_status: str
    created_at: datetime
    # Always True — reminds clients these are AI-generated values.
    ai_generated: bool = True

    model_config = {"from_attributes": True}


class TimelineResponse(BaseModel):
    """Paginated list of timeline events for a case."""

    case_id: uuid.UUID
    events: list[TimelineEventResponse]
    total: int
    # ISO timestamp of most recent event created_at, or null if no events.
    last_analyzed_at: datetime | None
    # True if analysis has been run at least once for this case.
    has_been_analyzed: bool


class ContradictionEvidenceResponse(BaseModel):
    """One side of a contradiction (source reference + quote)."""

    document_id: uuid.UUID | None
    document_name: str | None
    chunk_id: uuid.UUID | None
    quote: str


class TimelineContradictionResponse(BaseModel):
    """
    A potential discrepancy as returned by the API.

    DISCLAIMER: This is an AI-identified potential discrepancy.  It
    requires human review and does not constitute a legal finding.
    Both statements come from separately verified source excerpts.
    """

    id: uuid.UUID
    case_id: uuid.UUID
    category: str
    severity: str
    summary: str
    statement_a: str
    evidence_a: ContradictionEvidenceResponse
    statement_b: str
    evidence_b: ContradictionEvidenceResponse
    # Model estimate — not a calibrated probability.
    confidence: float
    review_status: str
    created_at: datetime
    # Always True — reminds clients these are AI-generated values.
    ai_generated: bool = True

    model_config = {"from_attributes": True}


class ContradictionsResponse(BaseModel):
    """List of contradictions for a case."""

    case_id: uuid.UUID
    contradictions: list[TimelineContradictionResponse]
    total: int


class AnalyzeResponse(BaseModel):
    """Result of a POST /timeline/analyze call."""

    case_id: uuid.UUID
    documents_analyzed: int
    events_extracted: int
    contradictions_found: int
    message: str
