"""
Tests for citation verification — added alongside Day 6 RAG feature.

Tests the end-to-end flow of citation verification:
  - Service layer (quote extraction, status assignment)
  - API endpoint: GET /chat/sources/{chunk_id}
  - Regression: existing RAG /chat/ask behaviour unchanged

Coverage:
  Service / unit:
    1.  No quoted text near [SOURCE:N] → status is "unverified".
    2.  Quoted text that IS in chunk content → status is "verified".
    3.  Quoted text that is NOT in chunk content → status is "invalid".
    4.  Out-of-range [SOURCE:99] still discarded (regression).
    5.  _extract_nearby_quote returns None when no double-quoted string present.
    6.  _extract_nearby_quote finds a quote within the window.
    7.  _extract_nearby_quote ignores quotes outside the window.
    8.  Citation without page number — page_number is None, handled correctly.

  Source detail API endpoint (GET /chat/sources/{chunk_id}):
    9.  Authorized user with valid chunk_id → 200.
    10. Authorized user + matching quoted_text → verified.
    11. Authorized user + non-matching quoted_text → invalid.
    12. Authorized user + no quoted_text → unverified.
    13. Non-member of chunk's case → 404 (resource-hiding).
    14. Missing chunk_id → 404.
    15. Unauthenticated request → 403.
    16. Malformed chunk_id (not a UUID) → 422.
    17. ADMIN can access chunk in any case.

  Regression (ask() and /chat/ask):
    18. ask() returns verification_status on every source.
    19. /chat/ask response includes verification_status in sources.
    20. Existing authorization isolation unaffected.
"""

import hashlib
import uuid

import pytest

from app.core.config import settings
from app.models.case_membership import CaseMemberRole
from app.models.document import Document, DocumentChunk, DocumentStatus, EmbeddingStatus
from app.models.user import UserRole
from app.services.embedding import FakeEmbeddingProvider
from app.services.llm_provider import FakeLLMProvider
from app.services.rag import (
    _extract_nearby_quote,
    _parse_and_validate_citations,
)
from app.services.search import SearchResult
from app.services.storage import LocalStorage, set_storage
from tests.helpers import add_membership, auth_headers, make_case, make_client, make_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def temp_storage(tmp_path):
    storage = LocalStorage(str(tmp_path / "storage"))
    set_storage(storage)
    yield storage
    set_storage(None)


@pytest.fixture(autouse=True)
def override_providers(monkeypatch):
    """Replace real providers with fakes for all citation verification tests."""
    fake_embed = FakeEmbeddingProvider(dim=384)
    fake_llm = FakeLLMProvider(response="[SOURCE:1] The document states clearly.")

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "_get_embedding_provider", lambda: fake_embed)
    monkeypatch.setattr(chat_module, "_get_llm_provider", lambda: fake_llm)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_result(
    content: str = "the contract terminates upon 30 days notice",
    document_name: str = "contract.pdf",
    page_number: int | None = 1,
    chunk_index: int = 0,
) -> SearchResult:
    return SearchResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name=document_name,
        case_id=uuid.uuid4(),
        chunk_index=chunk_index,
        page_number=page_number,
        content=content,
        similarity=0.85,
    )


def _make_doc_with_chunk(
    db,
    case_id: uuid.UUID,
    owner_id: uuid.UUID,
    content: str = "legal contract text",
    page_number: int | None = 1,
) -> tuple[Document, DocumentChunk]:
    doc = Document(
        case_id=case_id,
        uploaded_by=owner_id,
        original_filename="contract.pdf",
        storage_key=f"{case_id}/{uuid.uuid4()}",
        content_type="application/pdf",
        file_size=len(content),
        file_hash=hashlib.sha256(content.encode()).hexdigest(),
        status=DocumentStatus.READY,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    provider = FakeEmbeddingProvider(dim=384)
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        page_number=page_number,
        embedding=provider.embed([content])[0],
        embedding_model=settings.embedding_model,
        embedding_status=EmbeddingStatus.READY,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return doc, chunk


# ---------------------------------------------------------------------------
# 1–8: Service / unit tests
# ---------------------------------------------------------------------------


def test_no_quoted_text_gives_unverified_status():
    """1. When no quoted passage is near [SOURCE:N], status is 'unverified'."""
    chunk = _make_search_result(content="the contract terminates upon 30 days notice")
    answer = "According to [SOURCE:1], the contract has a termination clause."
    sources = _parse_and_validate_citations(answer, [chunk])

    assert len(sources) == 1
    assert sources[0].verification_status == "unverified"
    assert sources[0].quoted_text is None
    assert "no exact quotation" in sources[0].verification_note.lower()


def test_matching_quoted_text_gives_verified_status():
    """2. Quoted text that appears in the chunk → status is 'verified'."""
    content = "the contract terminates upon 30 days notice"
    chunk = _make_search_result(content=content)
    # Quote is an exact substring of the chunk content.
    answer = 'The clause states "terminates upon 30 days notice" [SOURCE:1].'
    sources = _parse_and_validate_citations(answer, [chunk])

    assert len(sources) == 1
    assert sources[0].verification_status == "verified"
    assert sources[0].quoted_text == "terminates upon 30 days notice"
    assert "verbatim" in sources[0].verification_note.lower()


def test_mismatched_quoted_text_gives_invalid_status():
    """3. Quoted text NOT in chunk → status is 'invalid'."""
    content = "the contract terminates upon 30 days notice"
    chunk = _make_search_result(content=content)
    # Quote is fabricated — not in the chunk.
    answer = 'The clause states "payment is due within 7 days" [SOURCE:1].'
    sources = _parse_and_validate_citations(answer, [chunk])

    assert len(sources) == 1
    assert sources[0].verification_status == "invalid"
    assert sources[0].quoted_text == "payment is due within 7 days"
    assert "does not appear" in sources[0].verification_note.lower()


def test_out_of_range_citation_still_discarded():
    """4. [SOURCE:99] with one chunk is discarded regardless of verification."""
    chunk = _make_search_result()
    answer = "See [SOURCE:1] and also [SOURCE:99]."
    sources = _parse_and_validate_citations(answer, [chunk])

    assert len(sources) == 1
    source_ns = {id(s) for s in sources}
    # Confirm only one source in result
    assert len(source_ns) == 1


def test_extract_nearby_quote_returns_none_without_quotes():
    """5. _extract_nearby_quote returns None when no double-quoted string present."""
    text = "According to [SOURCE:1] the contract is clear and unambiguous."
    result = _extract_nearby_quote(text, text.index("[SOURCE:1]"))
    assert result is None


def test_extract_nearby_quote_finds_quote_in_window():
    """6. _extract_nearby_quote returns quoted content within the window."""
    text = 'The clause states "terminate upon 30 days" [SOURCE:1] explicitly.'
    ref_pos = text.index("[SOURCE:1]")
    result = _extract_nearby_quote(text, ref_pos)
    assert result == "terminate upon 30 days"


def test_extract_nearby_quote_ignores_quotes_outside_window():
    """7. Quotes more than 500 chars before [SOURCE:N] are not returned."""
    far_quote = '"this is a distant quoted passage"'
    padding = "x" * 600
    ref = "[SOURCE:1]"
    text = far_quote + padding + ref
    ref_pos = text.index(ref)
    result = _extract_nearby_quote(text, ref_pos)
    assert result is None


def test_citation_without_page_number():
    """8. Chunk with page_number=None: citation has page_number=None, status assigned."""
    chunk = _make_search_result(content="no page metadata here", page_number=None)
    answer = "According to [SOURCE:1], this is fine."
    sources = _parse_and_validate_citations(answer, [chunk])

    assert len(sources) == 1
    assert sources[0].page_number is None
    assert sources[0].verification_status in ("verified", "unverified", "invalid")


# ---------------------------------------------------------------------------
# 9–17: Source detail API endpoint tests
# ---------------------------------------------------------------------------


def test_source_detail_authorized_user(client, db_session):
    """9. Authorized user with valid chunk_id → 200 with correct data."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    doc, chunk = _make_doc_with_chunk(db_session, case.id, user.id, content="contract clause text")

    resp = client.get(
        f"/chat/sources/{chunk.id}",
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunk_id"] == str(chunk.id)
    assert body["document_id"] == str(doc.id)
    assert body["content"] == "contract clause text"
    assert body["verification_status"] == "unverified"  # no quoted_text supplied


def test_source_detail_matching_quoted_text(client, db_session):
    """10. Authorized user + matching quoted_text query param → 'verified'."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    content = "the fee shall be paid within 30 days of invoice"
    _, chunk = _make_doc_with_chunk(db_session, case.id, user.id, content=content)

    resp = client.get(
        f"/chat/sources/{chunk.id}",
        params={"quoted_text": "paid within 30 days"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verification_status"] == "verified"
    assert body["quoted_text"] == "paid within 30 days"


def test_source_detail_non_matching_quoted_text(client, db_session):
    """11. Authorized user + non-matching quoted_text → 'invalid'."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    content = "the fee shall be paid within 30 days of invoice"
    _, chunk = _make_doc_with_chunk(db_session, case.id, user.id, content=content)

    resp = client.get(
        f"/chat/sources/{chunk.id}",
        params={"quoted_text": "payment is due immediately"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verification_status"] == "invalid"


def test_source_detail_no_quoted_text(client, db_session):
    """12. Authorized user + no quoted_text query param → 'unverified'."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _, chunk = _make_doc_with_chunk(db_session, case.id, user.id, content="some legal text")

    resp = client.get(
        f"/chat/sources/{chunk.id}",
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["verification_status"] == "unverified"
    assert resp.json()["quoted_text"] is None


def test_source_detail_unauthorized_case(client, db_session):
    """13. Non-member of chunk's case → 404 (resource-hiding)."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    outsider = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    _, chunk = _make_doc_with_chunk(db_session, case.id, owner.id, content="secret content")

    resp = client.get(
        f"/chat/sources/{chunk.id}",
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found."


def test_source_detail_missing_chunk(client, db_session):
    """14. Non-existent chunk_id → 404."""
    user = make_user(db_session, role=UserRole.LAWYER)
    missing_id = uuid.uuid4()

    resp = client.get(
        f"/chat/sources/{missing_id}",
        headers=auth_headers(user),
    )
    assert resp.status_code == 404


def test_source_detail_unauthenticated(client):
    """15. No auth token → 403."""
    resp = client.get(f"/chat/sources/{uuid.uuid4()}")
    assert resp.status_code == 403


def test_source_detail_malformed_chunk_id(client, db_session):
    """16. Malformed chunk_id (not a UUID) → 422 validation error."""
    user = make_user(db_session, role=UserRole.LAWYER)

    resp = client.get(
        "/chat/sources/not-a-valid-uuid",
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_source_detail_admin_access(client, db_session):
    """17. ADMIN can access chunks from any case without membership."""
    admin = make_user(db_session, role=UserRole.ADMIN)
    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    _, chunk = _make_doc_with_chunk(
        db_session, case.id, owner.id, content="admin-accessible content"
    )

    resp = client.get(
        f"/chat/sources/{chunk.id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "admin-accessible content"


# ---------------------------------------------------------------------------
# 18–20: Regression tests
# ---------------------------------------------------------------------------


def test_ask_sources_include_verification_status(db_session):
    """18. ask() includes verification_status on every returned source."""
    from app.services.rag import ask

    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id, content="contract clause content")

    result = ask(
        db=db_session,
        user=user,
        question="What does the contract say?",
        embedding_provider=FakeEmbeddingProvider(dim=384),
        llm_provider=FakeLLMProvider(response="[SOURCE:1] The contract clause content."),
    )

    assert result.insufficient_evidence is False
    assert len(result.sources) >= 1
    for source in result.sources:
        assert source.verification_status in ("verified", "unverified", "invalid")
        assert source.verification_note != ""


def test_chat_ask_response_includes_verification_fields(client, db_session):
    """19. POST /chat/ask response includes verification fields in sources."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id, content="contract clause content")

    resp = client.post(
        "/chat/ask",
        json={"question": "What does the contract say?", "case_id": str(case.id)},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "sources" in body
    for src in body["sources"]:
        assert "verification_status" in src
        assert "verification_note" in src
        assert "quoted_text" in src
        assert src["verification_status"] in ("verified", "unverified", "invalid")


def test_existing_authorization_isolation_unaffected(client, db_session):
    """20. User A cannot access User B's case chunks via the source detail endpoint."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)
    _, chunk_a = _make_doc_with_chunk(
        db_session, case_a.id, user_a.id, content="confidential content for case A"
    )

    # user_b tries to access user_a's chunk
    resp = client.get(
        f"/chat/sources/{chunk_a.id}",
        headers=auth_headers(user_b),
    )
    assert resp.status_code == 404
    # Confirm the response body does NOT contain the confidential content
    assert "confidential content" not in resp.text
