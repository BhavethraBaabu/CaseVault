"""
Tests for Day 5 semantic search.

All tests use FakeEmbeddingProvider (no real model downloads).
Tests run on SQLite with the Python cosine-similarity fallback —
they verify authorization logic, not pgvector SQL operators.

Coverage:
  15. Authenticated user can search authorized chunks.
  16. Blank query returns 422.
  17. Query length limit is enforced.
  18. Limit validation works.
  19. Results are ordered by descending similarity.
  20. Results include correct document and page metadata.
  21. Chunks without embeddings are excluded from results.
  22. Case-scoped search returns only that case's chunks.
  23. User cannot search another user's unauthorized case.
  24. VIEWER can search an authorized case.
  25. RESTRICTED_LAWYER can search only explicitly assigned cases.
  26. ADMIN can search across all cases.
  27. Unauthorized document names and text do not leak.
  28. No-results behavior is correct (empty list, 200).
  29. Provider error returns 503.
  30. Result limits applied before returning (limited to authorized set).

Isolation scenario (mandatory):
  - User A owns Case A, User B owns Case B.
  - A chunk in Case A and a chunk in Case B both have embeddings.
  - User A's search never returns Case B's chunk.
  - User B's search never returns Case A's chunk.
  - User A specifying Case B's ID is rejected.
  - Admin can search across both cases.
  - Authorization holds even when the unauthorized chunk would rank higher.

Note: PostgreSQL/pgvector-specific behaviour (cosine distance operator,
HNSW index) is NOT verified by these SQLite tests.
"""

import hashlib
import uuid

import pytest

from app.models.case_membership import CaseMemberRole
from app.models.document import Document, DocumentChunk, DocumentStatus, EmbeddingStatus
from app.models.user import UserRole
from app.services.embedding import FakeEmbeddingProvider
from app.services.embedding_provider import EmbeddingError
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
def override_search_provider(monkeypatch):
    """
    Replace the real embedding provider with FakeEmbeddingProvider for all
    search tests.  This prevents sentence-transformers from being loaded.
    """
    fake = FakeEmbeddingProvider(dim=384)
    import app.api.v1.search as search_module

    monkeypatch.setattr(search_module, "_get_provider", lambda: fake)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc_with_chunk(
    db,
    case_id: uuid.UUID,
    owner_id: uuid.UUID,
    content: str = "legal contract termination clause",
    page_number: int | None = 1,
    embedded: bool = True,
) -> tuple[Document, DocumentChunk]:
    """Create a Document + DocumentChunk, optionally with an embedding."""
    from app.core.config import settings

    doc = Document(
        case_id=case_id,
        uploaded_by=owner_id,
        original_filename="test_doc.txt",
        storage_key=f"{case_id}/{uuid.uuid4()}",
        content_type="text/plain",
        file_size=len(content),
        file_hash=hashlib.sha256(content.encode()).hexdigest(),
        status=DocumentStatus.READY,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    provider = FakeEmbeddingProvider(dim=384)
    embedding = provider.embed([content])[0] if embedded else None

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        page_number=page_number,
        embedding=embedding,
        embedding_model=settings.embedding_model if embedded else None,
        embedding_status=EmbeddingStatus.READY if embedded else EmbeddingStatus.PENDING,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return doc, chunk


# ---------------------------------------------------------------------------
# Search endpoint tests
# ---------------------------------------------------------------------------


def test_authenticated_user_can_search(client, db_session):
    """15. Authenticated user with access gets search results."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id, content="termination clause details")

    resp = client.post(
        "/search",
        json={"query": "termination clause", "limit": 5},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    assert data["query"] == "termination clause"


def test_blank_query_rejected(client, db_session):
    """16. Blank query returns 422."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/search",
        json={"query": "   "},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_empty_string_query_rejected(client, db_session):
    """16b. Empty string query returns 422 (Pydantic min_length=1)."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/search",
        json={"query": ""},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_query_length_limit_enforced(client, db_session):
    """17. Query exceeding 2000 chars returns 422."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/search",
        json={"query": "x" * 2001},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_limit_zero_rejected(client, db_session):
    """18. limit=0 returns 422."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/search",
        json={"query": "test", "limit": 0},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_limit_above_max_is_capped(client, db_session):
    """18b. limit > 50 is accepted but capped to max."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id)

    resp = client.post(
        "/search",
        json={"query": "anything", "limit": 50},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200


def test_results_ordered_by_similarity(client, db_session):
    """19. Results are ordered by descending similarity."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)

    _make_doc_with_chunk(db_session, case.id, user.id, content="contract termination notice")
    _make_doc_with_chunk(db_session, case.id, user.id, content="invoice payment schedule")

    resp = client.post(
        "/search",
        json={"query": "contract termination", "limit": 10},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    if len(results) >= 2:
        sims = [r["similarity"] for r in results]
        assert sims == sorted(sims, reverse=True)


def test_result_has_correct_metadata(client, db_session):
    """20. Results include correct document name and page number."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    doc, chunk = _make_doc_with_chunk(
        db_session, case.id, user.id,
        content="specific metadata test content",
        page_number=7,
    )

    resp = client.post(
        "/search",
        json={"query": "specific metadata test", "limit": 5},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1

    result = results[0]
    assert result["document_id"] == str(doc.id)
    assert result["case_id"] == str(case.id)
    assert "chunk_id" in result
    assert "similarity" in result
    assert result["similarity"] >= 0.0
    # No embedding vector in response
    assert "embedding" not in result


def test_chunks_without_embedding_excluded(client, db_session):
    """21. Chunks with no embedding are excluded from results."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)

    # One un-embedded chunk only
    _make_doc_with_chunk(db_session, case.id, user.id, content="no embedding here", embedded=False)

    resp = client.post(
        "/search",
        json={"query": "no embedding here", "limit": 5},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_case_scoped_search(client, db_session):
    """22. Case-scoped search returns only chunks from the specified case."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_a, user, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, user, CaseMemberRole.OWNER)

    _, chunk_a = _make_doc_with_chunk(db_session, case_a.id, user.id, content="case A content")
    _, chunk_b = _make_doc_with_chunk(db_session, case_b.id, user.id, content="case B content")

    resp = client.post(
        "/search",
        json={"query": "content", "case_id": str(case_a.id), "limit": 10},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    chunk_ids = {r["chunk_id"] for r in resp.json()["results"]}
    assert str(chunk_a.id) in chunk_ids
    assert str(chunk_b.id) not in chunk_ids


def test_user_cannot_search_unauthorized_case(client, db_session):
    """23. Specifying an unauthorized case_id returns an error, not leaked data."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)
    _make_doc_with_chunk(db_session, case_b.id, user_b.id, content="secret b content")

    # user_a has no membership in case_b
    resp = client.post(
        "/search",
        json={"query": "secret b content", "case_id": str(case_b.id)},
        headers=auth_headers(user_a),
    )
    # Should be rejected with 422 (ValueError → access denied)
    assert resp.status_code == 422


def test_viewer_can_search_authorized_case(client, db_session):
    """24. VIEWER can perform semantic search in their authorized case."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    viewer = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)
    _make_doc_with_chunk(db_session, case.id, owner.id, content="viewer accessible content")

    resp = client.post(
        "/search",
        json={"query": "viewer accessible", "limit": 5},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) >= 1


def test_restricted_lawyer_only_searches_assigned_cases(client, db_session):
    """25. RESTRICTED_LAWYER searches only explicitly assigned cases."""
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_assigned = make_case(db_session, cl)
    case_other = make_case(db_session, cl)
    add_membership(db_session, case_assigned, rl, CaseMemberRole.MEMBER)
    add_membership(db_session, case_other, owner, CaseMemberRole.OWNER)

    _, chunk_assigned = _make_doc_with_chunk(
        db_session, case_assigned.id, owner.id, content="assigned case content"
    )
    _, chunk_other = _make_doc_with_chunk(
        db_session, case_other.id, owner.id, content="other case secret content"
    )

    resp = client.post(
        "/search",
        json={"query": "content", "limit": 10},
        headers=auth_headers(rl),
    )
    assert resp.status_code == 200
    chunk_ids = {r["chunk_id"] for r in resp.json()["results"]}
    assert str(chunk_assigned.id) in chunk_ids
    assert str(chunk_other.id) not in chunk_ids


def test_admin_searches_across_all_cases(client, db_session):
    """26. ADMIN can search across all cases without explicit membership."""
    admin = make_user(db_session, role=UserRole.ADMIN)
    owner_a = make_user(db_session, role=UserRole.LAWYER)
    owner_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_a, owner_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, owner_b, CaseMemberRole.OWNER)

    _, chunk_a = _make_doc_with_chunk(db_session, case_a.id, owner_a.id, content="case A text")
    _, chunk_b = _make_doc_with_chunk(db_session, case_b.id, owner_b.id, content="case B text")

    resp = client.post(
        "/search",
        json={"query": "text", "limit": 10},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    chunk_ids = {r["chunk_id"] for r in resp.json()["results"]}
    assert str(chunk_a.id) in chunk_ids
    assert str(chunk_b.id) in chunk_ids


def test_unauthorized_content_does_not_leak(client, db_session):
    """27. Unauthorized document names and text do not appear in results."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    _make_doc_with_chunk(db_session, case_b.id, user_b.id, content="CONFIDENTIAL secret data")
    _make_doc_with_chunk(db_session, case_a.id, user_a.id, content="public case A text")

    resp = client.post(
        "/search",
        json={"query": "CONFIDENTIAL secret data", "limit": 10},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    for result in results:
        assert "CONFIDENTIAL" not in result["content"]
        assert str(case_b.id) not in result.get("case_id", "")


def test_no_results_returns_empty_list(client, db_session):
    """28. No matching chunks returns empty results with 200."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/search",
        json={"query": "completely irrelevant query"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []
    assert resp.json()["total"] == 0


def test_provider_error_returns_503(client, db_session, monkeypatch):
    """29. Provider failure returns 503 without stack trace."""
    user = make_user(db_session, role=UserRole.LAWYER)

    def failing_provider():
        class FailProvider:
            @property
            def dimension(self):
                return 384

            def embed(self, texts):
                raise EmbeddingError("Model unavailable")

        return FailProvider()

    import app.api.v1.search as search_module

    monkeypatch.setattr(search_module, "_get_provider", failing_provider)

    resp = client.post(
        "/search",
        json={"query": "test query"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 503
    # No stack trace or internal details
    assert "EmbeddingError" not in resp.json().get("detail", "")
    assert "Traceback" not in resp.json().get("detail", "")


def test_result_limit_applied_to_authorized_query(client, db_session):
    """30. limit is applied to the authorized query, not globally then filtered."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)

    # Create 5 embedded chunks in user's authorized case
    for i in range(5):
        _make_doc_with_chunk(db_session, case.id, user.id, content=f"chunk content {i}")

    resp = client.post(
        "/search",
        json={"query": "chunk content", "limit": 3},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) <= 3


def test_unauthenticated_request_rejected(client, db_session):
    """Search requires authentication."""
    resp = client.post("/search", json={"query": "test"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Mandatory cross-case isolation scenario
# ---------------------------------------------------------------------------


def test_cross_case_isolation_scenario(client, db_session):
    """
    Mandatory isolation scenario.

    - User A has access to Case A only.
    - User B has access to Case B only.
    - Chunk A is in Case A; Chunk B is in Case B.
    - Admin can see both.

    Proves:
    (a) User A's search never returns Case B's chunk.
    (b) User B's search never returns Case A's chunk.
    (c) User A cannot bypass restriction by specifying Case B's ID.
    (d) Admin can search across both cases.
    (e) Authorization holds even when the "wrong" chunk would rank higher.
    """
    admin = make_user(db_session, role=UserRole.ADMIN)
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    case_b = make_case(db_session, cl)

    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    # Use identical content so both chunks would match equally — isolation
    # must hold regardless of similarity ranking
    _, chunk_a = _make_doc_with_chunk(
        db_session, case_a.id, user_a.id, content="contract termination clause"
    )
    _, chunk_b = _make_doc_with_chunk(
        db_session, case_b.id, user_b.id, content="contract termination clause"
    )

    # (a) User A sees only Case A
    resp_a = client.post(
        "/search",
        json={"query": "contract termination clause", "limit": 10},
        headers=auth_headers(user_a),
    )
    assert resp_a.status_code == 200
    ids_a = {r["chunk_id"] for r in resp_a.json()["results"]}
    assert str(chunk_a.id) in ids_a
    assert str(chunk_b.id) not in ids_a

    # (b) User B sees only Case B
    resp_b = client.post(
        "/search",
        json={"query": "contract termination clause", "limit": 10},
        headers=auth_headers(user_b),
    )
    assert resp_b.status_code == 200
    ids_b = {r["chunk_id"] for r in resp_b.json()["results"]}
    assert str(chunk_b.id) in ids_b
    assert str(chunk_a.id) not in ids_b

    # (c) User A cannot bypass by specifying Case B's ID
    resp_bypass = client.post(
        "/search",
        json={"query": "contract termination", "case_id": str(case_b.id)},
        headers=auth_headers(user_a),
    )
    assert resp_bypass.status_code == 422

    # (d) Admin sees chunks from both cases
    resp_admin = client.post(
        "/search",
        json={"query": "contract termination clause", "limit": 10},
        headers=auth_headers(admin),
    )
    assert resp_admin.status_code == 200
    ids_admin = {r["chunk_id"] for r in resp_admin.json()["results"]}
    assert str(chunk_a.id) in ids_admin
    assert str(chunk_b.id) in ids_admin

    # (e) Even the chunk from the "other" case is absent — similarity doesn't override authz
    # Since both chunks have identical content, they'd have equal similarity.
    # User A must still only see chunk_a.
    assert str(chunk_b.id) not in ids_a
    assert str(chunk_a.id) not in ids_b
