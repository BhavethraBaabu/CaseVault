"""
Timeline event and contradiction models.

These records are created by the AI-assisted analysis pipeline and
represent extracted facts and potential discrepancies found in the
authorized documents of a single case.

Security model
--------------
  - timeline_events and timeline_contradictions are ALWAYS scoped to a
    single case_id.  The API layer verifies case membership before any
    access.
  - Source quotes are short excerpts (≤ 500 chars) — not full document
    text — to minimise sensitive data stored in the database.
  - The analysis pipeline never mixes documents from different cases.
  - All extraction results are labelled as AI-generated and require
    human review before being treated as legal facts.

Design decisions
----------------
  people / organizations
      Stored as JSON-encoded text (compatible with SQLite in tests and
      PostgreSQL in production).  No separate junction table needed for
      the current feature scope.

  event_date (nullable)
      Exact calendar date when known.  May be NULL when date_precision
      is UNKNOWN or APPROXIMATE without a specific date.

  date_precision
      Explicit enum rather than inferring from NULL event_date.
      Carries intent ("we know there is no date" vs "this is an exact
      date").

  review_status
      Workflow field for human reviewers.  AI sets UNREVIEWED; humans
      set REVIEWED or DISPUTED.

  source_quote
      Maximum 500 characters.  The pipeline verifies this is an actual
      substring of the source chunk content before persisting.  If the
      LLM hallucinates a quote that is not present, the event is
      discarded rather than persisted with a fabricated source.

  CASCADE on case_id FK
      Deleting a case removes all its timeline events and contradictions.
      This is appropriate because the events are derived from the case
      documents and have no independent value after case deletion.

  SET NULL on document/chunk FKs
      Deleting a document leaves events with a NULL source reference
      rather than cascade-deleting the event.  The event may still be
      useful for review even if the source document was removed.
"""

import json
import uuid
from datetime import UTC, date, datetime
from enum import Enum as PyEnum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DatePrecision(str, PyEnum):
    """
    How precisely the event date is known.

    EXACT       — specific calendar date (YYYY-MM-DD)
    MONTH       — month and year known, day uncertain
    YEAR        — year known, month/day uncertain
    APPROXIMATE — rough date mentioned ("early 2025", "around March")
    UNKNOWN     — no date information available
    """

    EXACT = "EXACT"
    MONTH = "MONTH"
    YEAR = "YEAR"
    APPROXIMATE = "APPROXIMATE"
    UNKNOWN = "UNKNOWN"


class EventType(str, PyEnum):
    MEETING = "MEETING"
    FILING = "FILING"
    PAYMENT = "PAYMENT"
    AGREEMENT = "AGREEMENT"
    TERMINATION = "TERMINATION"
    CORRESPONDENCE = "CORRESPONDENCE"
    HEARING = "HEARING"
    DEADLINE = "DEADLINE"
    OTHER = "OTHER"


class ReviewStatus(str, PyEnum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    DISPUTED = "DISPUTED"


class ContradictionCategory(str, PyEnum):
    DATE_CONFLICT = "DATE_CONFLICT"
    QUANTITY_CONFLICT = "QUANTITY_CONFLICT"
    FACT_CONFLICT = "FACT_CONFLICT"
    STATEMENT_CONFLICT = "STATEMENT_CONFLICT"
    OTHER = "OTHER"


class ContradictionSeverity(str, PyEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# Helper — JSON-encoded list field
# ---------------------------------------------------------------------------


def _encode_list(value: list[str] | None) -> str:
    """Encode a list of strings to a JSON text value."""
    return json.dumps(value or [])


def _decode_list(value: str | None) -> list[str]:
    """Decode a JSON text value to a list of strings."""
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# TimelineEvent
# ---------------------------------------------------------------------------


class TimelineEvent(Base):
    """
    A single event extracted from an authorized case document.

    Extraction is AI-assisted.  All fields are model-generated and must
    be reviewed by a human before being treated as legally accurate.

    Authorization:
      - Any case member (OWNER / MEMBER / VIEWER) may read events.
      - Events are created and deleted by the analysis pipeline, not
        directly by users.
      - An event's case_id must match the requested case_id on every API
        access — cross-case access is forbidden.
    """

    __tablename__ = "timeline_events"
    __table_args__ = (
        Index("ix_timeline_events_case_id", "case_id"),
        Index("ix_timeline_events_event_date", "event_date"),
        Index("ix_timeline_events_case_date", "case_id", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Source document — SET NULL if the document is later deleted.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Source chunk — SET NULL if the chunk is later deleted.
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ---- Event fields ----
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default=EventType.OTHER
    )

    # Nullable — unknown dates are explicitly represented
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_date_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_precision: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DatePrecision.UNKNOWN
    )

    # JSON-encoded list of person names
    _people_json: Mapped[str] = mapped_column("people", Text, nullable=False, default="[]")
    # JSON-encoded list of organization names
    _organizations_json: Mapped[str] = mapped_column(
        "organizations", Text, nullable=False, default="[]"
    )

    # Short verified excerpt from the source chunk (≤ 500 chars).
    # Verified to be an actual substring of the source text.
    source_quote: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Model confidence in [0.0, 1.0].  This is a model estimate, not a
    # calibrated probability.
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.UNREVIEWED
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships (load source doc name without eager-loading content)
    source_document: Mapped["Document | None"] = relationship(  # noqa: F821
        "Document", foreign_keys=[source_document_id], lazy="select"
    )
    source_chunk: Mapped["DocumentChunk | None"] = relationship(  # noqa: F821
        "DocumentChunk", foreign_keys=[source_chunk_id], lazy="select"
    )

    # ---- Python-level accessors for JSON list fields ----

    @property
    def people(self) -> list[str]:
        return _decode_list(self._people_json)

    @people.setter
    def people(self, value: list[str]) -> None:
        self._people_json = _encode_list(value)

    @property
    def organizations(self) -> list[str]:
        return _decode_list(self._organizations_json)

    @organizations.setter
    def organizations(self, value: list[str]) -> None:
        self._organizations_json = _encode_list(value)


# ---------------------------------------------------------------------------
# TimelineContradiction
# ---------------------------------------------------------------------------


class TimelineContradiction(Base):
    """
    A potential discrepancy between two statements in authorized case documents.

    Detection is AI-assisted.  Results are labelled as POTENTIAL discrepancies
    requiring human review.  The system does not determine legal truth.

    Both statements must have traceable source evidence.  Contradictions without
    verifiable quotes on both sides are not persisted.

    Authorization:
      - Any case member may read contradictions.
      - A contradiction's case_id must match the requested case_id on every
        API access — cross-case access is forbidden.
    """

    __tablename__ = "timeline_contradictions"
    __table_args__ = (
        Index("ix_timeline_contradictions_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ContradictionCategory.OTHER
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ContradictionSeverity.MEDIUM
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)

    # ---- Statement A ----
    statement_a: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_a_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_chunk_a_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Verified excerpt from source A (≤ 500 chars)
    source_quote_a: Mapped[str] = mapped_column(String(500), nullable=False)

    # ---- Statement B ----
    statement_b: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_b_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_chunk_b_id: Mapped[uuid.UUID | None] = mapped_column(
        SaUuid(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Verified excerpt from source B (≤ 500 chars)
    source_quote_b: Mapped[str] = mapped_column(String(500), nullable=False)

    # Model confidence in [0.0, 1.0] — not a calibrated probability.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.UNREVIEWED
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Relationships for source document names
    source_document_a: Mapped["Document | None"] = relationship(  # noqa: F821
        "Document", foreign_keys=[source_document_a_id], lazy="select"
    )
    source_document_b: Mapped["Document | None"] = relationship(  # noqa: F821
        "Document", foreign_keys=[source_document_b_id], lazy="select"
    )
