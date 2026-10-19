"""
AI Case Timeline + Contradiction Detector API.

Routes
------
POST   /cases/{case_id}/timeline/analyze         — extract events + detect contradictions
GET    /cases/{case_id}/timeline                  — list timeline events (paginated)
GET    /cases/{case_id}/timeline/events/{event_id} — get one event with source evidence
GET    /cases/{case_id}/contradictions            — list potential discrepancies
PATCH  /cases/{case_id}/contradictions/{contradiction_id} — update review status

Authorization
-------------
  All routes require authentication (get_current_user).
  Case access is verified by get_authorized_case before any data access.
  Timeline events and contradictions are scoped to case_id — a record
  from another case cannot be accessed by supplying a different event_id
  or contradiction_id (case_id is always part of the WHERE clause).

  VIEWER and above may read timeline and contradictions.
  OWNER and MEMBER may trigger analysis.
  OWNER and MEMBER may update review status.

Timing out
----------
  /analyze is synchronous.  For a demo with few documents it is fast
  enough.  In production, a background task queue is recommended for
  large cases.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_authorized_case,
    get_current_user,
    get_db,
    require_case_role,
)
from app.models.case import Case
from app.models.case_membership import CaseMemberRole
from app.models.timeline import TimelineContradiction, TimelineEvent
from app.models.user import User
from app.schemas.timeline import (
    AnalyzeResponse,
    ContradictionEvidenceResponse,
    ContradictionReviewUpdate,
    ContradictionsResponse,
    TimelineAnalyzeRequest,
    TimelineContradictionResponse,
    TimelineEventResponse,
    TimelineResponse,
)
from app.services.llm import get_llm_provider
from app.services.llm_provider import LLMError
from app.services.timeline import (
    analyze_case_timeline,
    get_contradictions,
    get_timeline_event,
    get_timeline_events,
    update_contradiction_review_status,
)

router = APIRouter(tags=["timeline"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_to_response(event: TimelineEvent) -> TimelineEventResponse:
    """Convert a TimelineEvent ORM object to its API response schema."""
    doc_name: str | None = None
    if event.source_document is not None:
        doc_name = event.source_document.original_filename

    return TimelineEventResponse(
        id=event.id,
        case_id=event.case_id,
        source_document_id=event.source_document_id,
        source_document_name=doc_name,
        source_chunk_id=event.source_chunk_id,
        title=event.title,
        description=event.description,
        event_type=event.event_type,
        event_date=event.event_date,
        event_date_end=event.event_date_end,
        date_precision=event.date_precision,
        people=event.people,
        organizations=event.organizations,
        source_quote=event.source_quote,
        source_page=event.source_page,
        extraction_confidence=event.extraction_confidence,
        review_status=event.review_status,
        created_at=event.created_at,
        ai_generated=True,
    )


def _contradiction_to_response(c: TimelineContradiction) -> TimelineContradictionResponse:
    """Convert a TimelineContradiction ORM object to its API response schema."""
    doc_a_name: str | None = None
    if c.source_document_a is not None:
        doc_a_name = c.source_document_a.original_filename

    doc_b_name: str | None = None
    if c.source_document_b is not None:
        doc_b_name = c.source_document_b.original_filename

    return TimelineContradictionResponse(
        id=c.id,
        case_id=c.case_id,
        category=c.category,
        severity=c.severity,
        summary=c.summary,
        statement_a=c.statement_a,
        evidence_a=ContradictionEvidenceResponse(
            document_id=c.source_document_a_id,
            document_name=doc_a_name,
            chunk_id=c.source_chunk_a_id,
            quote=c.source_quote_a,
        ),
        statement_b=c.statement_b,
        evidence_b=ContradictionEvidenceResponse(
            document_id=c.source_document_b_id,
            document_name=doc_b_name,
            chunk_id=c.source_chunk_b_id,
            quote=c.source_quote_b,
        ),
        confidence=c.confidence,
        review_status=c.review_status,
        created_at=c.created_at,
        ai_generated=True,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/timeline/analyze",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_200_OK,
)
def analyze_timeline(
    case_id: uuid.UUID,
    req: TimelineAnalyzeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    # OWNER and MEMBER may trigger analysis; VIEWER is read-only
    _case: Annotated[
        Case,
        Depends(
            require_case_role(CaseMemberRole.OWNER, CaseMemberRole.MEMBER)
        ),
    ],
) -> AnalyzeResponse:
    """
    Analyze eligible documents and extract a chronological timeline.

    Requires OWNER or MEMBER case role.

    force_reanalyze=true deletes existing events and contradictions for
    this case before re-running.  Use this when documents have changed.

    max_documents (1–10) limits how many READY documents are analyzed
    per call, bounding LLM cost and response time.

    Returns a summary of documents analyzed, events extracted, and
    potential contradictions found.  Events and contradictions are
    persisted and can be retrieved via the GET endpoints.

    DISCLAIMER: All extracted events are AI-generated and require human
    review before being treated as accurate.
    """
    try:
        llm = get_llm_provider()
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable. Configure LLM_API_KEY to enable timeline analysis.",
        ) from exc

    try:
        result = analyze_case_timeline(
            db=db,
            user=current_user,
            case_id=case_id,
            llm_provider=llm,
            max_documents=req.max_documents,
            force_reanalyze=req.force_reanalyze,
        )
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable. Please try again later.",
        ) from exc

    if result.documents_analyzed == 0:
        msg = (
            "No ready documents found for this case. "
            "Upload and process documents before running analysis."
        )
    else:
        msg = (
            f"Analysis complete. {result.events_extracted} event(s) extracted from "
            f"{result.documents_analyzed} document(s). "
            f"{result.contradictions_found} potential discrepancy(s) identified. "
            "All results require human review."
        )

    return AnalyzeResponse(
        case_id=case_id,
        documents_analyzed=result.documents_analyzed,
        events_extracted=result.events_extracted,
        contradictions_found=result.contradictions_found,
        message=msg,
    )


@router.get(
    "/cases/{case_id}/timeline",
    response_model=TimelineResponse,
)
def list_timeline(
    case_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _case: Annotated[Case, Depends(get_authorized_case)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> TimelineResponse:
    """
    Return a chronological list of timeline events for the case.

    Accessible to any case member (OWNER, MEMBER, VIEWER).
    Events without a date are returned after all dated events.
    """
    events, total = get_timeline_events(db, case_id, offset=offset, limit=limit)

    last_analyzed_at = None
    if events:
        last_analyzed_at = max(e.created_at for e in events)

    return TimelineResponse(
        case_id=case_id,
        events=[_event_to_response(e) for e in events],
        total=total,
        last_analyzed_at=last_analyzed_at,
        has_been_analyzed=total > 0,
    )


@router.get(
    "/cases/{case_id}/timeline/events/{event_id}",
    response_model=TimelineEventResponse,
)
def get_event(
    case_id: uuid.UUID,
    event_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _case: Annotated[Case, Depends(get_authorized_case)],
) -> TimelineEventResponse:
    """
    Return a single timeline event with its source evidence.

    The event must belong to the requested case_id.  Supplying an
    event_id from another case returns 404 — cross-case access is
    prevented at the query level.
    """
    event = get_timeline_event(db, case_id=case_id, event_id=event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return _event_to_response(event)


@router.get(
    "/cases/{case_id}/contradictions",
    response_model=ContradictionsResponse,
)
def list_contradictions(
    case_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _case: Annotated[Case, Depends(get_authorized_case)],
) -> ContradictionsResponse:
    """
    Return potential discrepancies identified for the case.

    Accessible to any case member.

    DISCLAIMER: These are AI-identified potential discrepancies.  They
    require human review and do not constitute legal findings.
    """
    contradictions, total = get_contradictions(db, case_id)
    return ContradictionsResponse(
        case_id=case_id,
        contradictions=[_contradiction_to_response(c) for c in contradictions],
        total=total,
    )


@router.patch(
    "/cases/{case_id}/contradictions/{contradiction_id}",
    response_model=TimelineContradictionResponse,
)
def review_contradiction(
    case_id: uuid.UUID,
    contradiction_id: uuid.UUID,
    update: ContradictionReviewUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    _case: Annotated[
        Case,
        Depends(
            require_case_role(CaseMemberRole.OWNER, CaseMemberRole.MEMBER)
        ),
    ],
) -> TimelineContradictionResponse:
    """
    Update the review_status of a potential discrepancy.

    Accepted values: UNREVIEWED | REVIEWED | DISPUTED

    Requires OWNER or MEMBER case role.

    The contradiction must belong to the requested case_id.  Cross-case
    access is prevented at the query level.
    """
    updated = update_contradiction_review_status(
        db,
        case_id=case_id,
        contradiction_id=contradiction_id,
        review_status=update.review_status.value,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Discrepancy not found",
        )
    return _contradiction_to_response(updated)
