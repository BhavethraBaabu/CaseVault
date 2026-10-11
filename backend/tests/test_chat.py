"""
Tests for the chat API endpoints — Day 6.

POST /chat/ask
GET  /chat/conversations
GET  /chat/conversations/{id}/messages
DELETE /chat/conversations/{id}

All tests use FakeEmbeddingProvider and FakeLLMProvider (no real API calls).
Tests run on SQLite with the Python cosine-similarity fallback.

Coverage:
  API / auth:
    1.  Unauthenticated /chat/ask returns 403.
    2.  /chat/ask with blank question returns 422.
    3.  /chat/ask with whitespace-only question returns 422.
    4.  /chat/ask when embedding provider unavailable returns 503.
    5.  /chat/ask when LLM provider unavailable returns 503.
    6.  /chat/ask returns answer with conversation_id.
    7.  /chat/ask returns insufficient_evidence=true when no chunks found.
    8.  /chat/ask includes source citations in response.
    9.  /chat/ask continues an existing conversation.
    10. /chat/ask with unauthorized case_id returns 422.
    11. /chat/ask with foreign conversation_id returns 422.

  Conversation management:
    12. GET /chat/conversations returns user's conversations.
    13. GET /chat/conversations does not return other user's conversations.
    14. ADMIN sees all conversations.
    15. GET /chat/conversations/{id}/messages returns messages.
    16. GET /chat/conversations/{id}/messages returns 404 for non-owner.
    17. DELETE /chat/conversations/{id} deletes the conversation.
    18. DELETE /chat/conversations/{id} returns 404 for non-owner.
    19. ADMIN can delete any conversation.
    20. GET /chat/conversations/{id}/messages returns 404 for missing ID.

  Authorization isolation (mandatory):
    21. User A's question never triggers retrieval of Case B's chunks.
    22. Prompt delivered to LLM contains only authorized evidence.
"""

import hashlib
import uuid

import pytest

from app.core.config import settings
from app.models.case_membership import CaseMemberRole
from app.models.document import Document, DocumentChunk, DocumentStatus, EmbeddingStatus
from app.models.user import UserRole
from app.services.embedding import FakeEmbeddingProvider
from app.services.embedding_provider import EmbeddingError
from app.services.llm_provider import FakeLLMProvider, LLMError
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
    """Replace real providers with fakes for all chat tests."""
    fake_embed = FakeEmbeddingProvider(dim=384)
    fake_llm = FakeLLMProvider(response="[SOURCE:1] The document states clearly.")

    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "_get_embedding_provider", lambda: fake_embed)
    monkeypatch.setattr(chat_module, "_get_llm_provider", lambda: fake_llm)

    return fake_embed, fake_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc_with_chunk(
    db,
    case_id: uuid.UUID,
    owner_id: uuid.UUID,
    content: str = "legal contract text",
) -> tuple[Document, DocumentChunk]:
    doc = Document(
        case_id=case_id,
        uploaded_by=owner_id,
        original_filename="test.pdf",
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
    embedding = provider.embed([content])[0]

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        page_number=1,
        embedding=embedding,
        embedding_model=settings.embedding_model,
        embedding_status=EmbeddingStatus.READY,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return doc, chunk


# ---------------------------------------------------------------------------
# Auth / input validation
# ---------------------------------------------------------------------------


def test_ask_requires_authentication(client):
    """1. Unauthenticated /chat/ask returns 403."""
    resp = client.post("/chat/ask", json={"question": "What is in the contract?"})
    assert resp.status_code == 403


def test_ask_blank_question_rejected(client, db_session):
    """2. Blank question returns 422."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/chat/ask",
        json={"question": ""},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_ask_whitespace_question_rejected(client, db_session):
    """3. Whitespace-only question returns 422."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/chat/ask",
        json={"question": "   "},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_ask_embedding_provider_error_returns_503(client, db_session, monkeypatch):
    """4. If the embedding provider raises, /chat/ask returns 503."""
    import app.api.v1.chat as chat_module

    def fail_embed():
        raise EmbeddingError("model unavailable")

    monkeypatch.setattr(chat_module, "_get_embedding_provider", fail_embed)

    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/chat/ask",
        json={"question": "What is in the contract?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 503
    assert "EmbeddingError" not in resp.json().get("detail", "")


def test_ask_llm_provider_not_configured_returns_503(client, db_session, monkeypatch):
    """5. If the LLM provider raises LLMError (e.g. missing API key), returns 503."""
    import app.api.v1.chat as chat_module

    def fail_llm():
        raise LLMError("LLM_API_KEY is not configured.")

    monkeypatch.setattr(chat_module, "_get_llm_provider", fail_llm)

    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/chat/ask",
        json={"question": "What is in the contract?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Successful ask scenarios
# ---------------------------------------------------------------------------


def test_ask_returns_answer_with_conversation_id(client, db_session):
    """6. Successful ask returns answer and conversation_id."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id, content="contract clause text")

    resp = client.post(
        "/chat/ask",
        json={"question": "What does the contract say?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "conversation_id" in data
    assert "insufficient_evidence" in data
    assert "sources" in data
    assert data["answer"] != ""
    # UUID is parseable
    uuid.UUID(data["conversation_id"])


def test_ask_returns_insufficient_evidence_when_no_chunks(client, db_session):
    """7. Returns insufficient_evidence=true when user has no documents."""
    user = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        "/chat/ask",
        json={"question": "What does the contract say?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["insufficient_evidence"] is True
    assert data["sources"] == []


def test_ask_includes_source_citations(client, db_session, monkeypatch):
    """8. Response includes source citations when LLM references [SOURCE:1]."""
    import app.api.v1.chat as chat_module

    citing_llm = FakeLLMProvider(response="[SOURCE:1] The contract clause states this.")
    monkeypatch.setattr(chat_module, "_get_llm_provider", lambda: citing_llm)

    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    doc, chunk = _make_doc_with_chunk(db_session, case.id, user.id, content="contract clause")

    resp = client.post(
        "/chat/ask",
        json={"question": "What does the contract say?"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert len(sources) >= 1
    assert sources[0]["document_id"] == str(doc.id)
    assert sources[0]["chunk_id"] == str(chunk.id)
    # Embedding vector must NOT be in response
    assert "embedding" not in sources[0]


def test_ask_continues_existing_conversation(client, db_session):
    """9. Supplying a conversation_id continues that conversation."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id, content="contract clause")

    # First ask
    resp1 = client.post(
        "/chat/ask",
        json={"question": "First question"},
        headers=auth_headers(user),
    )
    assert resp1.status_code == 200
    conv_id = resp1.json()["conversation_id"]

    # Second ask with same conversation_id
    resp2 = client.post(
        "/chat/ask",
        json={"question": "Follow-up question", "conversation_id": conv_id},
        headers=auth_headers(user),
    )
    assert resp2.status_code == 200
    assert resp2.json()["conversation_id"] == conv_id


def test_ask_unauthorized_case_returns_422(client, db_session):
    """10. Specifying a case_id the user doesn't have access to returns 422."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)
    _make_doc_with_chunk(db_session, case_b.id, user_b.id, content="secret content")

    resp = client.post(
        "/chat/ask",
        json={"question": "What is in the contract?", "case_id": str(case_b.id)},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422


def test_ask_foreign_conversation_id_returns_422(client, db_session):
    """11. Supplying another user's conversation_id returns 422."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user_a, CaseMemberRole.OWNER)
    _make_doc_with_chunk(db_session, case.id, user_a.id, content="contract text")

    # user_a creates a conversation
    resp1 = client.post(
        "/chat/ask",
        json={"question": "Question from A"},
        headers=auth_headers(user_a),
    )
    conv_id = resp1.json()["conversation_id"]

    # user_b tries to continue user_a's conversation
    resp2 = client.post(
        "/chat/ask",
        json={"question": "Hijack attempt", "conversation_id": conv_id},
        headers=auth_headers(user_b),
    )
    assert resp2.status_code == 422


# ---------------------------------------------------------------------------
# Conversation listing
# ---------------------------------------------------------------------------


def test_list_conversations_returns_user_conversations(client, db_session):
    """12. GET /chat/conversations returns authenticated user's conversations."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id)

    # Create a conversation via ask
    client.post(
        "/chat/ask",
        json={"question": "Hello?"},
        headers=auth_headers(user),
    )

    resp = client.get("/chat/conversations", headers=auth_headers(user))
    assert resp.status_code == 200
    conversations = resp.json()
    assert isinstance(conversations, list)
    assert len(conversations) >= 1


def test_list_conversations_excludes_other_users(client, db_session):
    """13. Users only see their own conversations."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user_a, CaseMemberRole.OWNER)
    _make_doc_with_chunk(db_session, case.id, user_a.id)

    # user_a creates a conversation
    client.post(
        "/chat/ask",
        json={"question": "User A question"},
        headers=auth_headers(user_a),
    )

    # user_b should see none
    resp = client.get("/chat/conversations", headers=auth_headers(user_b))
    assert resp.status_code == 200
    assert resp.json() == []


def test_admin_sees_all_conversations(client, db_session):
    """14. ADMIN user sees all conversations."""
    admin = make_user(db_session, role=UserRole.ADMIN)
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id)

    # user creates a conversation
    client.post(
        "/chat/ask",
        json={"question": "A user question"},
        headers=auth_headers(user),
    )

    resp = client.get("/chat/conversations", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


# ---------------------------------------------------------------------------
# Message retrieval
# ---------------------------------------------------------------------------


def test_get_messages_returns_conversation_messages(client, db_session):
    """15. GET /chat/conversations/{id}/messages returns the conversation's messages."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id, content="contract text")

    ask_resp = client.post(
        "/chat/ask",
        json={"question": "What does the contract say?"},
        headers=auth_headers(user),
    )
    conv_id = ask_resp.json()["conversation_id"]

    resp = client.get(f"/chat/conversations/{conv_id}/messages", headers=auth_headers(user))
    assert resp.status_code == 200
    messages = resp.json()
    assert isinstance(messages, list)
    assert len(messages) == 2
    roles = {m["role"] for m in messages}
    assert "user" in roles
    assert "assistant" in roles


def test_get_messages_returns_404_for_non_owner(client, db_session):
    """16. Non-owner gets 404 (resource-hiding)."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user_a, CaseMemberRole.OWNER)
    _make_doc_with_chunk(db_session, case.id, user_a.id)

    ask_resp = client.post(
        "/chat/ask",
        json={"question": "Question from A"},
        headers=auth_headers(user_a),
    )
    conv_id = ask_resp.json()["conversation_id"]

    resp = client.get(f"/chat/conversations/{conv_id}/messages", headers=auth_headers(user_b))
    assert resp.status_code == 404


def test_get_messages_returns_404_for_missing_conversation(client, db_session):
    """20. Non-existent conversation ID returns 404."""
    user = make_user(db_session, role=UserRole.LAWYER)
    missing_id = str(uuid.uuid4())
    resp = client.get(f"/chat/conversations/{missing_id}/messages", headers=auth_headers(user))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Conversation deletion
# ---------------------------------------------------------------------------


def test_delete_conversation_owner(client, db_session):
    """17. Owner can delete their conversation."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id)

    ask_resp = client.post(
        "/chat/ask",
        json={"question": "Question"},
        headers=auth_headers(user),
    )
    conv_id = ask_resp.json()["conversation_id"]

    del_resp = client.delete(f"/chat/conversations/{conv_id}", headers=auth_headers(user))
    assert del_resp.status_code == 204

    # Conversation should be gone
    get_resp = client.get(f"/chat/conversations/{conv_id}/messages", headers=auth_headers(user))
    assert get_resp.status_code == 404


def test_delete_conversation_returns_404_for_non_owner(client, db_session):
    """18. Non-owner trying to delete gets 404."""
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user_a, CaseMemberRole.OWNER)
    _make_doc_with_chunk(db_session, case.id, user_a.id)

    ask_resp = client.post(
        "/chat/ask",
        json={"question": "Question from A"},
        headers=auth_headers(user_a),
    )
    conv_id = ask_resp.json()["conversation_id"]

    resp = client.delete(f"/chat/conversations/{conv_id}", headers=auth_headers(user_b))
    assert resp.status_code == 404


def test_admin_can_delete_any_conversation(client, db_session):
    """19. ADMIN can delete any user's conversation."""
    admin = make_user(db_session, role=UserRole.ADMIN)
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)
    _make_doc_with_chunk(db_session, case.id, user.id)

    ask_resp = client.post(
        "/chat/ask",
        json={"question": "Question from user"},
        headers=auth_headers(user),
    )
    conv_id = ask_resp.json()["conversation_id"]

    resp = client.delete(f"/chat/conversations/{conv_id}", headers=auth_headers(admin))
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Mandatory authorization isolation scenario
# ---------------------------------------------------------------------------


def test_chat_cross_case_isolation(client, db_session, monkeypatch):
    """
    21-22. Mandatory isolation scenario:

    User A has access to Case A; User B to Case B.
    When user A asks a question:
      - Only Case A's chunk appears in the system prompt delivered to the LLM.
      - Case B's chunk is never present in the prompt.
    """
    import app.api.v1.chat as chat_module

    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    # Each case has a uniquely identifiable chunk
    _make_doc_with_chunk(db_session, case_a.id, user_a.id, content="CASE_A_UNIQUE_CONTENT_XYZ")
    _make_doc_with_chunk(db_session, case_b.id, user_b.id, content="CASE_B_UNIQUE_CONTENT_ABC")

    recording_llm = FakeLLMProvider(response="[SOURCE:1] Content found.")
    monkeypatch.setattr(chat_module, "_get_llm_provider", lambda: recording_llm)

    # User A asks a question
    resp = client.post(
        "/chat/ask",
        json={"question": "What is in the case?"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200

    # The prompt delivered to the LLM must include Case A's content
    # and must NEVER include Case B's content
    prompt = recording_llm.last_system_prompt or ""
    assert "CASE_A_UNIQUE_CONTENT_XYZ" in prompt
    assert "CASE_B_UNIQUE_CONTENT_ABC" not in prompt
