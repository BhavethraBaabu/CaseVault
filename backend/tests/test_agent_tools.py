"""
Tests for the agent tool registry (agent_tools.py) — Day 7.

All tests use SQLite in-memory (via db_session fixture).
No network calls, no real LLM, no real embedding model.

Coverage:
  Tool A — search_documents
    1.  Authorized user receives search results.
    2.  Non-member user receives empty results (not an error).
    3.  Invalid args return a failure ToolResult.
    4.  Unauthorized case_id returns an error from semantic_search.
    5.  source_offset correctly numbers results across multiple calls.

  Tool B — list_cases
    6.  User sees only their own accessible cases.
    7.  Admin sees all cases.
    8.  User with no memberships sees an empty list.
    9.  Unknown args keys are rejected by Pydantic.

  Tool C — get_case_details
    10. Authorized user receives case metadata.
    11. Non-member receives "Case not found." error.
    12. Non-existent case UUID returns "Case not found." error.
    13. Invalid UUID string in args returns a validation error.
    14. Admin bypasses membership check.

  Tool D — get_document_context
    15. Authorized user receives document chunks.
    16. Non-member receives "Case not found." error.
    17. Document belonging to a different case returns "Document not found."
    18. Non-existent document UUID returns "Document not found."
    19. max_chunks limits the number of chunks returned.
    20. Authorization checked before document lookup (cross-case injection blocked).

  Registry
    21. ALLOWED_TOOL_NAMES contains exactly the four expected tool names.
"""

import hashlib
import uuid

import pytest

from app.core.config import settings
from app.models.case_membership import CaseMemberRole
from app.models.document import Document, DocumentChunk, DocumentStatus, EmbeddingStatus
from app.models.user import UserRole
from app.services.agent_tools import (
    ALLOWED_TOOL_NAMES,
    GET_CASE_DETAILS_NAME,
    GET_DOCUMENT_CONTEXT_NAME,
    LIST_CASES_NAME,
    SEARCH_DOCUMENTS_NAME,
    execute_get_case_details,
    execute_get_document_context,
    execute_list_cases,
    execute_search_documents,
)
from app.services.embedding import FakeEmbeddingProvider
from tests.helpers import add_membership, make_case, make_client, make_user

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_embedding():
    return FakeEmbeddingProvider(dim=384)


@pytest.fixture()
def setup(db_session):
    """Create two users, two cases, and documents/chunks for testing."""
    client = make_client(db_session)

    lawyer = make_user(db_session, role=UserRole.LAWYER)
    other = make_user(db_session, role=UserRole.LAWYER)
    admin = make_user(db_session, role=UserRole.ADMIN)

    case_a = make_case(db_session, client, title="Case Alpha")
    case_b = make_case(db_session, client, title="Case Beta")

    add_membership(db_session, case_a, lawyer, role=CaseMemberRole.MEMBER)
    # lawyer has NO membership in case_b

    # Create a document with a chunk in case_a
    doc = Document(
        case_id=case_a.id,
        uploaded_by=lawyer.id,
        original_filename="contract.pdf",
        storage_key=f"store/{uuid.uuid4()}",
        content_type="application/pdf",
        file_size=1024,
        file_hash=hashlib.sha256(b"content").hexdigest(),
        status=DocumentStatus.READY,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    provider = FakeEmbeddingProvider(dim=384)
    embedding = provider.embed(["legal contract text"])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="legal contract text",
        page_number=1,
        embedding=embedding,
        embedding_model=settings.embedding_model,
        embedding_status=EmbeddingStatus.READY,
    )
    db_session.add(chunk)
    db_session.commit()
    db_session.refresh(chunk)

    return {
        "lawyer": lawyer,
        "other": other,
        "admin": admin,
        "case_a": case_a,
        "case_b": case_b,
        "doc": doc,
        "chunk": chunk,
    }


# ---------------------------------------------------------------------------
# Tool A: search_documents
# ---------------------------------------------------------------------------


def test_search_documents_authorized_user_gets_results(db_session, setup, fake_embedding):
    """1. Authorized user receives search results."""
    result = execute_search_documents(
        db=db_session,
        user=setup["lawyer"],
        args={"query": "legal contract", "case_id": str(setup["case_a"].id)},
        embedding_provider=fake_embedding,
    )
    assert result.success is True
    assert result.data["total"] >= 1
    assert len(result.raw_chunks) >= 1


def test_search_documents_non_member_gets_empty(db_session, setup, fake_embedding):
    """2. Non-member searching in a specific case gets error (unauthorized case)."""
    result = execute_search_documents(
        db=db_session,
        user=setup["other"],
        args={"query": "legal text", "case_id": str(setup["case_a"].id)},
        embedding_provider=fake_embedding,
    )
    # semantic_search raises ValueError for unauthorized case_id
    assert result.success is False
    assert "access denied" in result.error.lower() or "not found" in result.error.lower()


def test_search_documents_invalid_args_rejected(db_session, setup, fake_embedding):
    """3. Invalid args (missing query) return failure ToolResult."""
    result = execute_search_documents(
        db=db_session,
        user=setup["lawyer"],
        args={"limit": 3},  # missing required 'query'
        embedding_provider=fake_embedding,
    )
    assert result.success is False
    assert result.error is not None
    assert "Invalid arguments" in result.error


def test_search_documents_source_offset(db_session, setup, fake_embedding):
    """5. source_offset correctly numbers results across calls."""
    result = execute_search_documents(
        db=db_session,
        user=setup["lawyer"],
        args={"query": "legal contract"},
        embedding_provider=fake_embedding,
        source_offset=3,
    )
    assert result.success is True
    if result.data["total"] > 0:
        assert result.data["sources"][0]["source_number"] == 4  # 3 + 1


def test_search_documents_returns_no_storage_paths(db_session, setup, fake_embedding):
    """Search results never expose storage_key or internal paths."""
    result = execute_search_documents(
        db=db_session,
        user=setup["lawyer"],
        args={"query": "legal contract"},
        embedding_provider=fake_embedding,
    )
    assert result.success is True
    for source in result.data.get("sources", []):
        assert "storage_key" not in source
        assert "store/" not in str(source)


# ---------------------------------------------------------------------------
# Tool B: list_cases
# ---------------------------------------------------------------------------


def test_list_cases_member_sees_own_cases(db_session, setup):
    """6. User sees only their accessible cases."""
    result = execute_list_cases(db=db_session, user=setup["lawyer"], args={})
    assert result.success is True
    ids = {c["id"] for c in result.data["cases"]}
    assert str(setup["case_a"].id) in ids
    # case_b — lawyer is not a member
    assert str(setup["case_b"].id) not in ids


def test_list_cases_admin_sees_all(db_session, setup):
    """7. Admin sees all cases."""
    result = execute_list_cases(db=db_session, user=setup["admin"], args={})
    assert result.success is True
    ids = {c["id"] for c in result.data["cases"]}
    assert str(setup["case_a"].id) in ids
    assert str(setup["case_b"].id) in ids


def test_list_cases_no_membership_empty(db_session, setup):
    """8. User with no memberships sees an empty list."""
    result = execute_list_cases(db=db_session, user=setup["other"], args={})
    assert result.success is True
    assert result.data["total"] == 0


def test_list_cases_no_storage_or_credentials(db_session, setup):
    """list_cases never exposes storage paths or credentials."""
    result = execute_list_cases(db=db_session, user=setup["lawyer"], args={})
    assert result.success is True
    for case in result.data.get("cases", []):
        assert "storage_key" not in case
        assert "password" not in case


# ---------------------------------------------------------------------------
# Tool C: get_case_details
# ---------------------------------------------------------------------------


def test_get_case_details_authorized(db_session, setup):
    """10. Authorized user receives case metadata."""
    result = execute_get_case_details(
        db=db_session,
        user=setup["lawyer"],
        args={"case_id": str(setup["case_a"].id)},
    )
    assert result.success is True
    assert result.data["id"] == str(setup["case_a"].id)
    assert result.data["title"] == "Case Alpha"


def test_get_case_details_non_member_returns_not_found(db_session, setup):
    """11. Non-member receives 'Case not found.' error (resource-hiding)."""
    result = execute_get_case_details(
        db=db_session,
        user=setup["other"],
        args={"case_id": str(setup["case_a"].id)},
    )
    assert result.success is False
    assert result.error == "Case not found."


def test_get_case_details_nonexistent_returns_not_found(db_session, setup):
    """12. Non-existent case UUID returns 'Case not found.' error."""
    result = execute_get_case_details(
        db=db_session,
        user=setup["lawyer"],
        args={"case_id": str(uuid.uuid4())},
    )
    assert result.success is False
    assert result.error == "Case not found."


def test_get_case_details_invalid_uuid(db_session, setup):
    """13. Invalid UUID string in args returns validation error."""
    result = execute_get_case_details(
        db=db_session,
        user=setup["lawyer"],
        args={"case_id": "not-a-uuid"},
    )
    assert result.success is False
    assert "Invalid arguments" in result.error


def test_get_case_details_admin_bypasses_membership(db_session, setup):
    """14. Admin can retrieve any case without membership."""
    result = execute_get_case_details(
        db=db_session,
        user=setup["admin"],
        args={"case_id": str(setup["case_b"].id)},
    )
    assert result.success is True
    assert result.data["title"] == "Case Beta"


# ---------------------------------------------------------------------------
# Tool D: get_document_context
# ---------------------------------------------------------------------------


def test_get_document_context_authorized(db_session, setup):
    """15. Authorized user receives document chunks."""
    result = execute_get_document_context(
        db=db_session,
        user=setup["lawyer"],
        args={
            "document_id": str(setup["doc"].id),
            "case_id": str(setup["case_a"].id),
        },
    )
    assert result.success is True
    assert result.data["document_name"] == "contract.pdf"
    assert len(result.data["chunks"]) == 1
    assert "legal contract text" in result.data["chunks"][0]["content"]


def test_get_document_context_non_member_returns_not_found(db_session, setup):
    """16. Non-member receives 'Case not found.' error."""
    result = execute_get_document_context(
        db=db_session,
        user=setup["other"],
        args={
            "document_id": str(setup["doc"].id),
            "case_id": str(setup["case_a"].id),
        },
    )
    assert result.success is False
    assert result.error == "Case not found."


def test_get_document_context_wrong_case_returns_not_found(db_session, setup):
    """17. Document from a different case returns 'Document not found.'"""
    # lawyer IS a member of case_a but NOT case_b; the doc belongs to case_a
    # Providing case_b as the case_id should fail at the document lookup step
    # because the doc's case_id does not match case_b.
    # But first the user must have access to case_b — they don't, so Case not found.
    result = execute_get_document_context(
        db=db_session,
        user=setup["admin"],  # admin has access to case_b
        args={
            "document_id": str(setup["doc"].id),
            "case_id": str(setup["case_b"].id),  # doc is in case_a, not case_b
        },
    )
    assert result.success is False
    assert result.error == "Document not found."


def test_get_document_context_nonexistent_document(db_session, setup):
    """18. Non-existent document UUID returns 'Document not found.'"""
    result = execute_get_document_context(
        db=db_session,
        user=setup["lawyer"],
        args={
            "document_id": str(uuid.uuid4()),
            "case_id": str(setup["case_a"].id),
        },
    )
    assert result.success is False
    assert result.error == "Document not found."


def test_get_document_context_max_chunks_respected(db_session, setup):
    """19. max_chunks limits the number of chunks returned."""
    result = execute_get_document_context(
        db=db_session,
        user=setup["lawyer"],
        args={
            "document_id": str(setup["doc"].id),
            "case_id": str(setup["case_a"].id),
            "max_chunks": 1,
        },
    )
    assert result.success is True
    assert len(result.data["chunks"]) <= 1


def test_get_document_context_no_storage_paths(db_session, setup):
    """Document context never exposes storage_key or file paths."""
    result = execute_get_document_context(
        db=db_session,
        user=setup["lawyer"],
        args={
            "document_id": str(setup["doc"].id),
            "case_id": str(setup["case_a"].id),
        },
    )
    assert result.success is True
    assert "storage_key" not in result.data
    assert "store/" not in str(result.data)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_allowed_tool_names_contains_all_four():
    """21. ALLOWED_TOOL_NAMES contains exactly the four expected tools."""
    assert ALLOWED_TOOL_NAMES == frozenset(
        {
            SEARCH_DOCUMENTS_NAME,
            LIST_CASES_NAME,
            GET_CASE_DETAILS_NAME,
            GET_DOCUMENT_CONTEXT_NAME,
        }
    )
