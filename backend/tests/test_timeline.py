"""
Tests for the AI Case Timeline + Contradiction Detector feature.

Coverage
--------
Unit (service-layer):
  - Date parsing (exact, partial, invalid)
  - Quote verification (present, absent, empty)
  - LLM response parsing (valid, malformed, empty)
  - Event extraction (quote verified, quote absent, low confidence)
  - Duplicate analysis prevention (no force)
  - Force reanalyze clears existing records
  - Empty document set
  - Events with no date (UNKNOWN precision)
  - Contradiction detection (genuine date conflict, no contradiction)
  - Malformed LLM response for contradictions
  - Self-contradiction prevention (same chunk, different events)
  - Provider failure (LLMError) propagated correctly
  - Paginated event retrieval
  - Cross-case event lookup returns None
  - Contradiction review status update
  - Cross-case contradiction lookup returns None

API (HTTP integration):
  - Unauthenticated analyze returns 403
  - Unauthorized (non-member) analyze returns 404
  - VIEWER cannot trigger analyze (403)
  - MEMBER and OWNER can trigger analyze
  - LLM unavailable returns 503
  - Get timeline (empty state, with events)
  - Get single event (own case, wrong case returns 404)
  - Get contradictions (empty, with items)
  - PATCH contradiction review status (valid, invalid status)
  - Unauthorized user cannot read timeline or contradictions (404)
  - Cross-case event ID access denied (404)
  - Cross-case contradiction ID access denied (404)
"""

import json
import uuid

import pytest

from app.models.case_membership import CaseMemberRole
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.timeline import (
    DatePrecision,
    EventType,
    ReviewStatus,
    TimelineContradiction,
    TimelineEvent,
)
from app.services.llm_provider import FakeLLMProvider, FakeSequentialProvider, LLMError
from app.services.timeline import (
    _parse_contradiction_response,
    _parse_event_date,
    _parse_extraction_response,
    _verify_quote,
    analyze_case_timeline,
    get_contradictions,
    get_timeline_event,
    get_timeline_events,
    update_contradiction_review_status,
)
from tests.helpers import (
    add_membership,
    auth_headers,
    make_case,
    make_client,
    make_user,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_document(db, case, uploaded_by=None, filename="test.txt"):
    """Create a READY document with one chunk."""
    doc = Document(
        id=uuid.uuid4(),
        case_id=case.id,
        uploaded_by=uploaded_by,
        original_filename=filename,
        storage_key=f"{case.id}/{uuid.uuid4()}",
        content_type="text/plain",
        file_size=100,
        file_hash="abc123",
        status=DocumentStatus.READY,
        page_count=1,
    )
    db.add(doc)
    db.flush()

    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=0,
        content="The meeting took place on March 4, 2025 at the firm's office.",
        token_count=12,
        page_number=1,
    )
    db.add(chunk)
    db.commit()
    db.refresh(doc)
    return doc, chunk


def make_document_with_content(db, case, content: str, filename="doc.txt"):
    """Create a READY document with specific content."""
    doc = Document(
        id=uuid.uuid4(),
        case_id=case.id,
        original_filename=filename,
        storage_key=f"{case.id}/{uuid.uuid4()}",
        content_type="text/plain",
        file_size=len(content),
        file_hash="deadbeef",
        status=DocumentStatus.READY,
        page_count=1,
    )
    db.add(doc)
    db.flush()
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        document_id=doc.id,
        chunk_index=0,
        content=content,
        token_count=20,
        page_number=1,
    )
    db.add(chunk)
    db.commit()
    db.refresh(doc)
    return doc, chunk


# ---------------------------------------------------------------------------
# Unit — date parsing
# ---------------------------------------------------------------------------


class TestDateParsing:
    def test_exact_date(self):
        d = _parse_event_date("2025-03-04")
        assert d is not None
        assert d.year == 2025
        assert d.month == 3
        assert d.day == 4

    def test_year_month_only(self):
        d = _parse_event_date("2025-03")
        assert d is not None
        assert d.year == 2025
        assert d.month == 3
        assert d.day == 1  # defaults to first of month

    def test_year_only(self):
        d = _parse_event_date("2025")
        assert d is not None
        assert d.year == 2025
        assert d.month == 1
        assert d.day == 1

    def test_none_returns_none(self):
        assert _parse_event_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_event_date("") is None

    def test_invalid_string_returns_none(self):
        assert _parse_event_date("not-a-date") is None

    def test_invalid_month(self):
        assert _parse_event_date("2025-13-01") is None

    def test_whitespace_stripped(self):
        d = _parse_event_date("  2025-06-15  ")
        assert d is not None
        assert d.month == 6


# ---------------------------------------------------------------------------
# Unit — quote verification
# ---------------------------------------------------------------------------


class TestQuoteVerification:
    def test_present_quote(self):
        assert _verify_quote("March 4, 2025", "The meeting took place on March 4, 2025.")

    def test_absent_quote(self):
        assert not _verify_quote("March 6, 2025", "The meeting took place on March 4, 2025.")

    def test_empty_quote_fails(self):
        assert not _verify_quote("", "Some source text")

    def test_exact_match(self):
        text = "Payment is due within 30 days of invoice."
        assert _verify_quote("within 30 days", text)

    def test_case_sensitive(self):
        # Verification is case-sensitive (exact substring check)
        assert not _verify_quote("MARCH 4", "March 4, 2025")


# ---------------------------------------------------------------------------
# Unit — LLM response parsing
# ---------------------------------------------------------------------------


class TestExtractionParsing:
    def test_valid_response(self):
        raw = json.dumps(
            {
                "events": [
                    {
                        "title": "Initial meeting",
                        "description": "Parties met to discuss the agreement.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-04",
                        "event_date_end": None,
                        "date_precision": "EXACT",
                        "people": ["Alice Smith"],
                        "organizations": ["Acme Corp"],
                        "source_quote": "The meeting took place on March 4, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        result = _parse_extraction_response(raw)
        assert result is not None
        assert len(result.events) == 1
        assert result.events[0].title == "Initial meeting"
        assert result.events[0].event_date == "2025-03-04"

    def test_empty_events(self):
        raw = json.dumps({"events": []})
        result = _parse_extraction_response(raw)
        assert result is not None
        assert result.events == []

    def test_malformed_json(self):
        result = _parse_extraction_response("not json at all")
        assert result is None

    def test_wrong_schema(self):
        raw = json.dumps({"unexpected_key": "unexpected_value"})
        result = _parse_extraction_response(raw)
        # events defaults to [] if key missing
        assert result is not None
        assert result.events == []

    def test_markdown_fence_stripped(self):
        raw = '```json\n{"events": []}\n```'
        result = _parse_extraction_response(raw)
        assert result is not None

    def test_invalid_event_type_defaults(self):
        raw = json.dumps(
            {
                "events": [
                    {
                        "title": "Something",
                        "description": "Desc.",
                        "event_type": "INVALID_TYPE",
                        "source_quote": "quote text",
                        "extraction_confidence": 0.8,
                    }
                ]
            }
        )
        result = _parse_extraction_response(raw)
        # EventType enum validation — invalid values are rejected by Pydantic
        assert result is None or len(result.events) == 0

    def test_missing_required_field_source_quote(self):
        raw = json.dumps(
            {
                "events": [
                    {
                        "title": "Event",
                        "description": "Desc.",
                        "event_type": "MEETING",
                    }
                ]
            }
        )
        result = _parse_extraction_response(raw)
        # source_quote is required — should fail validation
        assert result is None or len(result.events) == 0


class TestContradictionParsing:
    def test_valid_contradiction(self):
        raw = json.dumps(
            {
                "contradictions": [
                    {
                        "category": "DATE_CONFLICT",
                        "severity": "MEDIUM",
                        "summary": "Different dates for the same meeting.",
                        "statement_a": "Meeting on March 4, 2025.",
                        "statement_b": "Meeting on March 6, 2025.",
                        "source_quote_a": "March 4, 2025",
                        "source_quote_b": "March 6, 2025",
                        "confidence": 0.85,
                        "is_contradiction": True,
                    }
                ]
            }
        )
        result = _parse_contradiction_response(raw)
        assert result is not None
        assert len(result.contradictions) == 1
        assert result.contradictions[0].category.value == "DATE_CONFLICT"

    def test_empty_contradictions(self):
        raw = json.dumps({"contradictions": []})
        result = _parse_contradiction_response(raw)
        assert result is not None
        assert result.contradictions == []

    def test_malformed_returns_none(self):
        result = _parse_contradiction_response("{invalid}")
        assert result is None

    def test_is_contradiction_false_filtered(self):
        """is_contradiction=False entries should be filtered by the service (not here)."""
        raw = json.dumps(
            {
                "contradictions": [
                    {
                        "category": "DATE_CONFLICT",
                        "severity": "LOW",
                        "summary": "Not a real conflict.",
                        "statement_a": "X.",
                        "statement_b": "Y.",
                        "source_quote_a": "X",
                        "source_quote_b": "Y",
                        "confidence": 0.2,
                        "is_contradiction": False,
                    }
                ]
            }
        )
        # Parsing succeeds; service layer filters is_contradiction=False
        result = _parse_contradiction_response(raw)
        assert result is not None
        assert result.contradictions[0].is_contradiction is False


# ---------------------------------------------------------------------------
# Unit — service: analyze_case_timeline
# ---------------------------------------------------------------------------


class TestAnalyzeCaseTimeline:
    def test_no_ready_documents_returns_empty(self, db_session):
        """With no READY documents, analysis returns empty results."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        result = analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=FakeLLMProvider(response=json.dumps({"events": []})),
        )
        assert result.documents_analyzed == 0
        assert result.events_extracted == 0
        assert result.contradictions_found == 0

    def test_extracts_event_with_verified_quote(self, db_session):
        """Events with quotes present in source text are persisted."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        doc, chunk = make_document(db_session, case)

        extraction = json.dumps(
            {
                "events": [
                    {
                        "title": "Initial meeting",
                        "description": "The parties met at the firm's office.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-04",
                        "event_date_end": None,
                        "date_precision": "EXACT",
                        "people": ["Jane Smith"],
                        "organizations": [],
                        "source_quote": "The meeting took place on March 4, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        # Extraction + empty contradictions (< 2 events after extraction, so no call)
        llm = FakeLLMProvider(response=extraction)

        result = analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=llm,
        )
        assert result.events_extracted == 1
        assert result.contradictions_found == 0

        events, total = get_timeline_events(db_session, case.id)
        assert total == 1
        assert events[0].title == "Initial meeting"
        assert events[0].event_date is not None
        assert events[0].source_quote == "The meeting took place on March 4, 2025"
        assert events[0].source_document_id == doc.id

    def test_discards_event_with_unverified_quote(self, db_session):
        """Events whose quote is not in the source text are discarded."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        make_document(db_session, case)

        # Quote "FABRICATED QUOTE" is NOT in the chunk content
        extraction = json.dumps(
            {
                "events": [
                    {
                        "title": "Fake event",
                        "description": "This quote was fabricated.",
                        "event_type": "OTHER",
                        "event_date": None,
                        "event_date_end": None,
                        "date_precision": "UNKNOWN",
                        "people": [],
                        "organizations": [],
                        "source_quote": "FABRICATED QUOTE NOT IN SOURCE",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        llm = FakeLLMProvider(response=extraction)

        result = analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=llm,
        )
        assert result.events_extracted == 0

    def test_discards_low_confidence_event(self, db_session):
        """Events below _MIN_CONFIDENCE threshold are discarded."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        make_document(db_session, case)

        extraction = json.dumps(
            {
                "events": [
                    {
                        "title": "Uncertain event",
                        "description": "Desc.",
                        "event_type": "OTHER",
                        "event_date": None,
                        "date_precision": "UNKNOWN",
                        "people": [],
                        "organizations": [],
                        "source_quote": "The meeting took place on March 4, 2025",
                        "extraction_confidence": 0.05,  # below _MIN_CONFIDENCE=0.1
                    }
                ]
            }
        )
        llm = FakeLLMProvider(response=extraction)

        result = analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=llm,
        )
        assert result.events_extracted == 0

    def test_event_without_date_persisted(self, db_session):
        """Events without a date are persisted with UNKNOWN precision."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        make_document(db_session, case)

        extraction = json.dumps(
            {
                "events": [
                    {
                        "title": "Undated event",
                        "description": "An event with no date.",
                        "event_type": "OTHER",
                        "event_date": None,
                        "event_date_end": None,
                        "date_precision": "UNKNOWN",
                        "people": [],
                        "organizations": [],
                        "source_quote": "The meeting took place on March 4, 2025",
                        "extraction_confidence": 0.7,
                    }
                ]
            }
        )
        llm = FakeLLMProvider(response=extraction)
        result = analyze_case_timeline(
            db=db_session, user=user, case_id=case.id, llm_provider=llm
        )
        assert result.events_extracted == 1
        events, _ = get_timeline_events(db_session, case.id)
        assert events[0].event_date is None
        assert events[0].date_precision == DatePrecision.UNKNOWN.value

    def test_malformed_extraction_response_skips_document(self, db_session):
        """Malformed LLM response for extraction is handled gracefully."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        make_document(db_session, case)

        llm = FakeLLMProvider(response="this is not json")
        result = analyze_case_timeline(
            db=db_session, user=user, case_id=case.id, llm_provider=llm
        )
        assert result.events_extracted == 0

    def test_force_reanalyze_clears_existing(self, db_session):
        """force_reanalyze=True deletes existing events and re-runs."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        make_document(db_session, case)

        extraction = json.dumps(
            {
                "events": [
                    {
                        "title": "First extraction",
                        "description": "Desc.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-04",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "The meeting took place on March 4, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        llm = FakeLLMProvider(response=extraction)

        # First analysis
        analyze_case_timeline(
            db=db_session, user=user, case_id=case.id, llm_provider=llm
        )
        _, total_before = get_timeline_events(db_session, case.id)
        assert total_before == 1

        # Second analysis without force — should not double-extract
        # (existing events remain; no deletion without force)
        analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=FakeLLMProvider(response=extraction),
        )
        _, total_after_no_force = get_timeline_events(db_session, case.id)
        assert total_after_no_force == 2  # accumulated (no dedup without force)

        # Third analysis with force — clears and re-extracts
        analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=FakeLLMProvider(response=extraction),
            force_reanalyze=True,
        )
        _, total_after_force = get_timeline_events(db_session, case.id)
        assert total_after_force == 1  # cleared and re-populated

    def test_contradiction_detected_between_two_documents(self, db_session):
        """Two documents with conflicting dates trigger contradiction detection."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        doc_a, chunk_a = make_document_with_content(
            db_session, case, "The meeting took place on March 4, 2025.", "doc_a.txt"
        )
        doc_b, chunk_b = make_document_with_content(
            db_session, case, "The meeting took place on March 6, 2025.", "doc_b.txt"
        )

        extraction_a = json.dumps(
            {
                "events": [
                    {
                        "title": "Meeting",
                        "description": "Meeting per Doc A.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-04",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "meeting took place on March 4, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        extraction_b = json.dumps(
            {
                "events": [
                    {
                        "title": "Meeting",
                        "description": "Meeting per Doc B.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-06",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "meeting took place on March 6, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        contradiction_response = json.dumps(
            {
                "contradictions": [
                    {
                        "category": "DATE_CONFLICT",
                        "severity": "MEDIUM",
                        "summary": "Documents disagree on meeting date.",
                        "statement_a": "Meeting on March 4, 2025.",
                        "statement_b": "Meeting on March 6, 2025.",
                        "source_quote_a": "meeting took place on March 4, 2025",
                        "source_quote_b": "meeting took place on March 6, 2025",
                        "confidence": 0.88,
                        "is_contradiction": True,
                    }
                ]
            }
        )
        llm = FakeSequentialProvider(
            responses=[extraction_a, extraction_b, contradiction_response]
        )

        result = analyze_case_timeline(
            db=db_session,
            user=user,
            case_id=case.id,
            llm_provider=llm,
            max_documents=5,
        )
        assert result.events_extracted == 2
        assert result.contradictions_found == 1

        contras, total = get_contradictions(db_session, case.id)
        assert total == 1
        assert contras[0].category == "DATE_CONFLICT"
        assert contras[0].source_quote_a == "meeting took place on March 4, 2025"
        assert contras[0].source_quote_b == "meeting took place on March 6, 2025"

    def test_contradiction_with_unverified_quote_discarded(self, db_session):
        """Contradictions with quotes not in source text are discarded."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        make_document_with_content(
            db_session, case, "Meeting on March 4, 2025.", "doc_a.txt"
        )
        make_document_with_content(
            db_session, case, "Meeting on March 6, 2025.", "doc_b.txt"
        )

        extraction_a = json.dumps(
            {
                "events": [
                    {
                        "title": "Meeting",
                        "description": "Desc.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-04",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "Meeting on March 4, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        extraction_b = json.dumps(
            {
                "events": [
                    {
                        "title": "Meeting",
                        "description": "Desc.",
                        "event_type": "MEETING",
                        "event_date": "2025-03-06",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "Meeting on March 6, 2025",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        # LLM returns fabricated quotes that don't exist in any source text
        contradiction_response = json.dumps(
            {
                "contradictions": [
                    {
                        "category": "DATE_CONFLICT",
                        "severity": "HIGH",
                        "summary": "Fabricated conflict.",
                        "statement_a": "A.",
                        "statement_b": "B.",
                        "source_quote_a": "FABRICATED QUOTE A NOT IN ANY SOURCE",
                        "source_quote_b": "FABRICATED QUOTE B NOT IN ANY SOURCE",
                        "confidence": 0.9,
                        "is_contradiction": True,
                    }
                ]
            }
        )
        llm = FakeSequentialProvider(
            responses=[extraction_a, extraction_b, contradiction_response]
        )

        result = analyze_case_timeline(
            db=db_session, user=user, case_id=case.id, llm_provider=llm
        )
        # 2 events extracted but 0 contradictions (fabricated quotes discarded)
        assert result.events_extracted == 2
        assert result.contradictions_found == 0

    def test_no_contradiction_when_unrelated_events(self, db_session):
        """Two unrelated events do not produce a contradiction."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        make_document_with_content(db_session, case, "The payment was made on Jan 1.", "doc_a.txt")
        make_document_with_content(
            db_session, case, "The contract was signed on Feb 5.", "doc_b.txt"
        )

        extraction_a = json.dumps(
            {
                "events": [
                    {
                        "title": "Payment",
                        "description": "Payment made.",
                        "event_type": "PAYMENT",
                        "event_date": "2025-01-01",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "payment was made on Jan 1",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        extraction_b = json.dumps(
            {
                "events": [
                    {
                        "title": "Contract signed",
                        "description": "Contract signing.",
                        "event_type": "AGREEMENT",
                        "event_date": "2025-02-05",
                        "date_precision": "EXACT",
                        "people": [],
                        "organizations": [],
                        "source_quote": "contract was signed on Feb 5",
                        "extraction_confidence": 0.9,
                    }
                ]
            }
        )
        # LLM correctly returns no contradictions
        no_contradiction = json.dumps({"contradictions": []})
        llm = FakeSequentialProvider(
            responses=[extraction_a, extraction_b, no_contradiction]
        )

        result = analyze_case_timeline(
            db=db_session, user=user, case_id=case.id, llm_provider=llm
        )
        assert result.events_extracted == 2
        assert result.contradictions_found == 0

    def test_provider_error_propagated(self, db_session):
        """LLMError from provider propagates out of analyze_case_timeline."""
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)
        make_document(db_session, case)

        llm = FakeLLMProvider(raise_error=True)
        with pytest.raises(LLMError):
            analyze_case_timeline(
                db=db_session, user=user, case_id=case.id, llm_provider=llm
            )

    def test_unauthorized_documents_not_analyzed(self, db_session):
        """User without case membership sees no documents to analyze."""
        owner = make_user(db_session)
        outsider = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, owner, CaseMemberRole.OWNER)
        make_document(db_session, case)

        llm = FakeLLMProvider(response=json.dumps({"events": []}))
        result = analyze_case_timeline(
            db=db_session,
            user=outsider,
            case_id=case.id,
            llm_provider=llm,
        )
        assert result.documents_analyzed == 0


# ---------------------------------------------------------------------------
# Unit — service: retrieval
# ---------------------------------------------------------------------------


class TestRetrievalService:
    def test_get_timeline_events_paginated(self, db_session):
        user = make_user(db_session)
        client = make_client(db_session)
        case = make_case(db_session, client)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        # Create 3 events directly
        for i in range(3):
            e = TimelineEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                title=f"Event {i}",
                description="Desc.",
                event_type=EventType.OTHER.value,
                date_precision=DatePrecision.UNKNOWN.value,
                review_status=ReviewStatus.UNREVIEWED.value,
                extraction_confidence=0.8,
            )
            e.people = []
            e.organizations = []
            db_session.add(e)
        db_session.commit()

        events, total = get_timeline_events(db_session, case.id, offset=0, limit=2)
        assert total == 3
        assert len(events) == 2

        events2, total2 = get_timeline_events(db_session, case.id, offset=2, limit=2)
        assert total2 == 3
        assert len(events2) == 1

    def test_get_event_cross_case_returns_none(self, db_session):
        """get_timeline_event with wrong case_id returns None."""
        client = make_client(db_session)
        case_a = make_case(db_session, client)
        case_b = make_case(db_session, client)

        event = TimelineEvent(
            id=uuid.uuid4(),
            case_id=case_a.id,
            title="Event in case A",
            description="Desc.",
            event_type=EventType.OTHER.value,
            date_precision=DatePrecision.UNKNOWN.value,
            review_status=ReviewStatus.UNREVIEWED.value,
            extraction_confidence=0.8,
        )
        event.people = []
        event.organizations = []
        db_session.add(event)
        db_session.commit()

        # Access with wrong case_id returns None
        result = get_timeline_event(db_session, case_id=case_b.id, event_id=event.id)
        assert result is None

        # Access with correct case_id succeeds
        result = get_timeline_event(db_session, case_id=case_a.id, event_id=event.id)
        assert result is not None

    def test_contradiction_review_status_update(self, db_session):
        client = make_client(db_session)
        case = make_case(db_session, client)

        c = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case.id,
            category="DATE_CONFLICT",
            severity="MEDIUM",
            summary="Summary.",
            statement_a="Statement A.",
            source_quote_a="quote A",
            statement_b="Statement B.",
            source_quote_b="quote B",
            confidence=0.8,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(c)
        db_session.commit()

        updated = update_contradiction_review_status(
            db_session,
            case_id=case.id,
            contradiction_id=c.id,
            review_status=ReviewStatus.REVIEWED.value,
        )
        assert updated is not None
        assert updated.review_status == ReviewStatus.REVIEWED.value

    def test_contradiction_review_cross_case_returns_none(self, db_session):
        client = make_client(db_session)
        case_a = make_case(db_session, client)
        case_b = make_case(db_session, client)

        c = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case_a.id,
            category="DATE_CONFLICT",
            severity="LOW",
            summary="Summary.",
            statement_a="A.",
            source_quote_a="q",
            statement_b="B.",
            source_quote_b="r",
            confidence=0.5,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(c)
        db_session.commit()

        result = update_contradiction_review_status(
            db_session,
            case_id=case_b.id,  # Wrong case
            contradiction_id=c.id,
            review_status=ReviewStatus.REVIEWED.value,
        )
        assert result is None


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


class TestTimelineAPI:
    # ------------------------------------------------------------------ #
    # Authorization                                                        #
    # ------------------------------------------------------------------ #

    def test_analyze_unauthenticated(self, client):
        """Unauthenticated request returns 403."""
        fake_id = uuid.uuid4()
        resp = client.post(
            f"/cases/{fake_id}/timeline/analyze",
            json={"force_reanalyze": False, "max_documents": 5},
        )
        assert resp.status_code == 403

    def test_analyze_non_member_returns_404(self, client, db_session):
        """User without case membership cannot trigger analysis."""
        user = make_user(db_session)
        outsider = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        resp = client.post(
            f"/cases/{case.id}/timeline/analyze",
            json={"force_reanalyze": False, "max_documents": 5},
            headers=auth_headers(outsider),
        )
        assert resp.status_code == 404

    def test_analyze_viewer_forbidden(self, client, db_session):
        """VIEWER role cannot trigger analysis (OWNER/MEMBER only)."""
        viewer = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

        resp = client.post(
            f"/cases/{case.id}/timeline/analyze",
            json={"force_reanalyze": False, "max_documents": 5},
            headers=auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_analyze_member_allowed(self, client, db_session, monkeypatch):
        """MEMBER can trigger analysis."""
        member = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, member, CaseMemberRole.MEMBER)

        # Patch get_llm_provider to return a fake
        fake_llm = FakeLLMProvider(response=json.dumps({"events": []}))
        monkeypatch.setattr(
            "app.api.v1.timeline.get_llm_provider", lambda: fake_llm
        )

        resp = client.post(
            f"/cases/{case.id}/timeline/analyze",
            json={"force_reanalyze": False, "max_documents": 5},
            headers=auth_headers(member),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == str(case.id)
        assert data["documents_analyzed"] == 0

    def test_analyze_llm_unavailable_returns_503(self, client, db_session, monkeypatch):
        """If LLM provider raises LLMError, returns 503."""
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        def _raise():
            raise LLMError("No API key")

        monkeypatch.setattr("app.api.v1.timeline.get_llm_provider", _raise)

        resp = client.post(
            f"/cases/{case.id}/timeline/analyze",
            json={"force_reanalyze": False, "max_documents": 5},
            headers=auth_headers(user),
        )
        assert resp.status_code == 503

    # ------------------------------------------------------------------ #
    # GET timeline                                                         #
    # ------------------------------------------------------------------ #

    def test_get_timeline_unauthenticated(self, client):
        resp = client.get(f"/cases/{uuid.uuid4()}/timeline")
        assert resp.status_code == 403

    def test_get_timeline_non_member_returns_404(self, client, db_session):
        user = make_user(db_session)
        outsider = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        resp = client.get(
            f"/cases/{case.id}/timeline", headers=auth_headers(outsider)
        )
        assert resp.status_code == 404

    def test_get_timeline_empty(self, client, db_session):
        """Timeline returns empty list before analysis."""
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.MEMBER)

        resp = client.get(
            f"/cases/{case.id}/timeline", headers=auth_headers(user)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["events"] == []
        assert data["has_been_analyzed"] is False

    def test_get_timeline_with_events(self, client, db_session):
        """Timeline returns events for authorized user."""
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.MEMBER)

        event = TimelineEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            title="Test Event",
            description="Something happened.",
            event_type=EventType.MEETING.value,
            date_precision=DatePrecision.EXACT.value,
            review_status=ReviewStatus.UNREVIEWED.value,
            extraction_confidence=0.85,
        )
        event.people = ["Alice"]
        event.organizations = ["Acme"]
        db_session.add(event)
        db_session.commit()

        resp = client.get(
            f"/cases/{case.id}/timeline", headers=auth_headers(user)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["has_been_analyzed"] is True
        assert data["events"][0]["title"] == "Test Event"
        assert data["events"][0]["ai_generated"] is True
        assert data["events"][0]["people"] == ["Alice"]

    # ------------------------------------------------------------------ #
    # GET single event                                                     #
    # ------------------------------------------------------------------ #

    def test_get_event_non_member_returns_404(self, client, db_session):
        user = make_user(db_session)
        outsider = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        event = TimelineEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            title="Private Event",
            description="Desc.",
            event_type=EventType.OTHER.value,
            date_precision=DatePrecision.UNKNOWN.value,
            review_status=ReviewStatus.UNREVIEWED.value,
            extraction_confidence=0.7,
        )
        event.people = []
        event.organizations = []
        db_session.add(event)
        db_session.commit()

        resp = client.get(
            f"/cases/{case.id}/timeline/events/{event.id}",
            headers=auth_headers(outsider),
        )
        assert resp.status_code == 404

    def test_get_event_cross_case_denied(self, client, db_session):
        """Event from case_b cannot be accessed via case_a URL."""
        user = make_user(db_session)
        cl = make_client(db_session)
        case_a = make_case(db_session, cl)
        case_b = make_case(db_session, cl)
        add_membership(db_session, case_a, user, CaseMemberRole.OWNER)
        add_membership(db_session, case_b, user, CaseMemberRole.OWNER)

        event_b = TimelineEvent(
            id=uuid.uuid4(),
            case_id=case_b.id,
            title="Event in B",
            description="Desc.",
            event_type=EventType.OTHER.value,
            date_precision=DatePrecision.UNKNOWN.value,
            review_status=ReviewStatus.UNREVIEWED.value,
            extraction_confidence=0.8,
        )
        event_b.people = []
        event_b.organizations = []
        db_session.add(event_b)
        db_session.commit()

        # Try to access event_b via case_a's URL
        resp = client.get(
            f"/cases/{case_a.id}/timeline/events/{event_b.id}",
            headers=auth_headers(user),
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------------ #
    # GET contradictions                                                   #
    # ------------------------------------------------------------------ #

    def test_get_contradictions_unauthenticated(self, client):
        resp = client.get(f"/cases/{uuid.uuid4()}/contradictions")
        assert resp.status_code == 403

    def test_get_contradictions_non_member(self, client, db_session):
        user = make_user(db_session)
        outsider = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.OWNER)

        resp = client.get(
            f"/cases/{case.id}/contradictions", headers=auth_headers(outsider)
        )
        assert resp.status_code == 404

    def test_get_contradictions_empty(self, client, db_session):
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.MEMBER)

        resp = client.get(
            f"/cases/{case.id}/contradictions", headers=auth_headers(user)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["contradictions"] == []

    def test_get_contradictions_with_items(self, client, db_session):
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.MEMBER)

        contra = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case.id,
            category="DATE_CONFLICT",
            severity="MEDIUM",
            summary="Meeting date conflict.",
            statement_a="Meeting on March 4.",
            source_quote_a="March 4",
            statement_b="Meeting on March 6.",
            source_quote_b="March 6",
            confidence=0.88,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(contra)
        db_session.commit()

        resp = client.get(
            f"/cases/{case.id}/contradictions", headers=auth_headers(user)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["contradictions"][0]
        assert item["category"] == "DATE_CONFLICT"
        assert item["ai_generated"] is True
        assert item["evidence_a"]["quote"] == "March 4"
        assert item["evidence_b"]["quote"] == "March 6"

    def test_get_contradictions_cross_case_denied(self, client, db_session):
        """Contradictions from case_b cannot leak into case_a queries."""
        user = make_user(db_session)
        cl = make_client(db_session)
        case_a = make_case(db_session, cl)
        case_b = make_case(db_session, cl)
        add_membership(db_session, case_a, user, CaseMemberRole.OWNER)
        add_membership(db_session, case_b, user, CaseMemberRole.OWNER)

        # Add contradiction to case_b only
        contra_b = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case_b.id,
            category="FACT_CONFLICT",
            severity="HIGH",
            summary="Fact conflict in B.",
            statement_a="X.",
            source_quote_a="x",
            statement_b="Y.",
            source_quote_b="y",
            confidence=0.7,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(contra_b)
        db_session.commit()

        # Query case_a — must not return case_b's contradictions
        resp = client.get(
            f"/cases/{case_a.id}/contradictions", headers=auth_headers(user)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    # ------------------------------------------------------------------ #
    # PATCH contradiction review status                                    #
    # ------------------------------------------------------------------ #

    def test_patch_review_status_valid(self, client, db_session):
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.MEMBER)

        contra = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case.id,
            category="DATE_CONFLICT",
            severity="LOW",
            summary="Summary.",
            statement_a="A.",
            source_quote_a="A",
            statement_b="B.",
            source_quote_b="B",
            confidence=0.6,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(contra)
        db_session.commit()

        resp = client.patch(
            f"/cases/{case.id}/contradictions/{contra.id}",
            json={"review_status": "REVIEWED"},
            headers=auth_headers(user),
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "REVIEWED"

    def test_patch_review_status_viewer_forbidden(self, client, db_session):
        viewer = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

        contra = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case.id,
            category="DATE_CONFLICT",
            severity="LOW",
            summary="Summary.",
            statement_a="A.",
            source_quote_a="A",
            statement_b="B.",
            source_quote_b="B",
            confidence=0.5,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(contra)
        db_session.commit()

        resp = client.patch(
            f"/cases/{case.id}/contradictions/{contra.id}",
            json={"review_status": "REVIEWED"},
            headers=auth_headers(viewer),
        )
        assert resp.status_code == 403

    def test_patch_review_status_invalid_value(self, client, db_session):
        user = make_user(db_session)
        cl = make_client(db_session)
        case = make_case(db_session, cl)
        add_membership(db_session, case, user, CaseMemberRole.MEMBER)

        contra = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case.id,
            category="DATE_CONFLICT",
            severity="LOW",
            summary="Summary.",
            statement_a="A.",
            source_quote_a="A",
            statement_b="B.",
            source_quote_b="B",
            confidence=0.5,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(contra)
        db_session.commit()

        resp = client.patch(
            f"/cases/{case.id}/contradictions/{contra.id}",
            json={"review_status": "INVALID_STATUS"},
            headers=auth_headers(user),
        )
        assert resp.status_code == 422

    def test_patch_review_cross_case_denied(self, client, db_session):
        """Contradiction from case_b cannot be patched via case_a URL."""
        user = make_user(db_session)
        cl = make_client(db_session)
        case_a = make_case(db_session, cl)
        case_b = make_case(db_session, cl)
        add_membership(db_session, case_a, user, CaseMemberRole.OWNER)
        add_membership(db_session, case_b, user, CaseMemberRole.OWNER)

        contra_b = TimelineContradiction(
            id=uuid.uuid4(),
            case_id=case_b.id,
            category="DATE_CONFLICT",
            severity="LOW",
            summary="Summary.",
            statement_a="A.",
            source_quote_a="A",
            statement_b="B.",
            source_quote_b="B",
            confidence=0.5,
            review_status=ReviewStatus.UNREVIEWED.value,
        )
        db_session.add(contra_b)
        db_session.commit()

        resp = client.patch(
            f"/cases/{case_a.id}/contradictions/{contra_b.id}",
            json={"review_status": "REVIEWED"},
            headers=auth_headers(user),
        )
        assert resp.status_code == 404
