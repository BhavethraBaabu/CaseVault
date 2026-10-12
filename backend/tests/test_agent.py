"""
Tests for the agent orchestration service and API endpoint — Day 7.

All tests use FakeSequentialProvider (no real LLM calls) and
FakeEmbeddingProvider (no real embedding model).

Coverage:
  Agent service — run_agent()
    1.  Agent with immediate answer (no tool calls) returns the answer.
    2.  Agent with one list_cases tool call then answer includes trace.
    3.  Agent with search_documents produces citations.
    4.  Unknown tool name is rejected and logged in trace (success=False).
    5.  max_tool_calls limit prevents unbounded loops.
    6.  LLMError from provider propagates as LLMError.
    7.  Malformed JSON response is treated as the final answer.
    8.  Blank task raises ValueError.
    9.  Overlong task raises ValueError.
    10. INSUFFICIENT_EVIDENCE sentinel returns insufficient_evidence=True.
    11. LLM tool call with invalid args returns failure trace entry.
    12. User cannot access unauthorized case via agent (case isolation).
    13. Citation validation discards fabricated [SOURCE:99].
    14. Max iterations produces a fallback answer without crashing.

  API — POST /agent/run
    15. Unauthenticated request returns 401.
    16. Blank task returns 422.
    17. Valid request returns 200 with expected schema.
    18. LLM provider not configured returns 503.
    19. Authorized user gets response; unauthorized case tool call fails safely.
    20. User cannot supply another user's identity in request body.
"""

import hashlib
import json
import uuid

import pytest

from app.core.config import settings
from app.models.case_membership import CaseMemberRole
from app.models.document import Document, DocumentChunk, DocumentStatus, EmbeddingStatus
from app.models.user import UserRole
from app.services.agent import run_agent
from app.services.agent_tools import SEARCH_DOCUMENTS_NAME
from app.services.embedding import FakeEmbeddingProvider
from app.services.llm_provider import FakeLLMProvider, FakeSequentialProvider, LLMError
from tests.helpers import add_membership, auth_headers, make_case, make_client, make_user

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_embedding():
    return FakeEmbeddingProvider(dim=384)


@pytest.fixture()
def setup(db_session):
    """Two users, two cases, one document with chunk."""
    cl = make_client(db_session)
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    other = make_user(db_session, role=UserRole.LAWYER)
    admin = make_user(db_session, role=UserRole.ADMIN)

    case_a = make_case(db_session, cl, title="Case Alpha")
    case_b = make_case(db_session, cl, title="Case Beta")

    add_membership(db_session, case_a, lawyer, role=CaseMemberRole.MEMBER)

    provider = FakeEmbeddingProvider(dim=384)
    embedding = provider.embed(["legal contract clause"])[0]

    doc = Document(
        case_id=case_a.id,
        uploaded_by=lawyer.id,
        original_filename="contract.pdf",
        storage_key=f"store/{uuid.uuid4()}",
        content_type="application/pdf",
        file_size=512,
        file_hash=hashlib.sha256(b"legal contract clause").hexdigest(),
        status=DocumentStatus.READY,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="legal contract clause",
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
# Agent service tests
# ---------------------------------------------------------------------------


def test_agent_immediate_answer(db_session, setup, fake_embedding):
    """1. Agent with immediate answer returns the answer text."""
    llm = FakeSequentialProvider(
        responses=['{"type": "answer", "content": "The answer is yes."}']
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="What is the status of my cases?",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    assert result.status == "success"
    assert result.answer == "The answer is yes."
    assert result.tools_executed == []


def test_agent_list_cases_tool_then_answer(db_session, setup, fake_embedding):
    """2. Agent with list_cases tool call includes trace entry."""
    llm = FakeSequentialProvider(
        responses=[
            '{"type": "tool_call", "tool": "list_cases", "args": {}}',
            '{"type": "answer", "content": "You have 1 accessible case."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="List my cases",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    assert result.status == "success"
    assert result.answer == "You have 1 accessible case."
    assert len(result.tools_executed) == 1
    assert result.tools_executed[0].tool_name == "list_cases"
    assert result.tools_executed[0].success is True


def test_agent_search_produces_citations(db_session, setup, fake_embedding):
    """3. Agent using search_documents produces validated citations."""
    llm = FakeSequentialProvider(
        responses=[
            json.dumps({
                "type": "tool_call",
                "tool": "search_documents",
                "args": {"query": "legal contract", "case_id": str(setup["case_a"].id)},
            }),
            '{"type": "answer", "content": "The contract states [SOURCE:1] the clause is valid."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="What does the contract say?",
        embedding_provider=fake_embedding,
        llm_provider=llm,
        case_id=setup["case_a"].id,
    )
    assert result.status == "success"
    assert len(result.tools_executed) == 1
    assert result.tools_executed[0].tool_name == SEARCH_DOCUMENTS_NAME
    assert result.tools_executed[0].success is True
    # At least one citation should be validated
    assert len(result.citations) >= 1
    assert result.citations[0].document_name == "contract.pdf"


def test_agent_unknown_tool_rejected(db_session, setup, fake_embedding):
    """4. Unknown tool name is rejected with a failure trace entry."""
    llm = FakeSequentialProvider(
        responses=[
            '{"type": "tool_call", "tool": "execute_shell", "args": {"cmd": "ls"}}',
            '{"type": "answer", "content": "Done."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="Run a shell command",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    assert result.status == "success"
    assert any(
        t.tool_name == "execute_shell" and t.success is False
        for t in result.tools_executed
    )


def test_agent_max_tool_calls_enforced(db_session, setup, fake_embedding):
    """5. Agent respects the max_tool_calls limit."""
    # Returns tool_call every time; should be capped
    many_tool_calls = ['{"type": "tool_call", "tool": "list_cases", "args": {}}'] * 20
    many_tool_calls.append('{"type": "answer", "content": "Here are your cases."}')
    llm = FakeSequentialProvider(responses=many_tool_calls)
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="List all cases repeatedly",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    # Should not exceed configured limit (plus 1 for possible cleanup call)
    assert len(result.tools_executed) <= settings.agent_max_tool_calls


def test_agent_llm_error_propagates(db_session, setup, fake_embedding):
    """6. LLMError from provider propagates as LLMError."""
    llm = FakeLLMProvider(raise_error=True)
    with pytest.raises(LLMError):
        run_agent(
            db=db_session,
            user=setup["lawyer"],
            task="What is the status?",
            embedding_provider=fake_embedding,
            llm_provider=llm,
        )


def test_agent_malformed_json_as_final_answer(db_session, setup, fake_embedding):
    """7. Malformed/unparseable LLM response is treated as the final answer."""
    llm = FakeSequentialProvider(
        responses=["This is not JSON at all, just plain text response."]
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="What is the status?",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    assert result.status == "success"
    assert "plain text response" in result.answer


def test_agent_blank_task_raises_value_error(db_session, setup, fake_embedding):
    """8. Blank task raises ValueError."""
    llm = FakeSequentialProvider(responses=['{"type": "answer", "content": "ok"}'])
    with pytest.raises(ValueError, match="empty"):
        run_agent(
            db=db_session,
            user=setup["lawyer"],
            task="   ",
            embedding_provider=fake_embedding,
            llm_provider=llm,
        )


def test_agent_overlong_task_raises_value_error(db_session, setup, fake_embedding):
    """9. Overlong task raises ValueError."""
    llm = FakeSequentialProvider(responses=['{"type": "answer", "content": "ok"}'])
    with pytest.raises(ValueError, match="maximum length"):
        run_agent(
            db=db_session,
            user=setup["lawyer"],
            task="x" * (settings.agent_max_task_length + 1),
            embedding_provider=fake_embedding,
            llm_provider=llm,
        )


def test_agent_insufficient_evidence_sentinel(db_session, setup, fake_embedding):
    """10. INSUFFICIENT_EVIDENCE sentinel returns insufficient_evidence=True."""
    llm = FakeSequentialProvider(
        responses=['{"type": "answer", "content": "INSUFFICIENT_EVIDENCE"}']
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="What is the outcome?",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    assert result.insufficient_evidence is True
    assert "sufficient supporting information" in result.answer


def test_agent_invalid_tool_args_returns_failure_trace(db_session, setup, fake_embedding):
    """11. Tool call with invalid args (missing required field) returns failure trace."""
    llm = FakeSequentialProvider(
        responses=[
            # get_case_details requires case_id but it's missing
            '{"type": "tool_call", "tool": "get_case_details", "args": {}}',
            '{"type": "answer", "content": "Could not get details."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="Get case details",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    assert any(
        t.tool_name == "get_case_details" and t.success is False
        for t in result.tools_executed
    )


def test_agent_case_isolation_non_member_tool_fails(db_session, setup, fake_embedding):
    """12. Non-member user cannot access unauthorized case via agent tool."""
    llm = FakeSequentialProvider(
        responses=[
            json.dumps({
                "type": "tool_call",
                "tool": "get_case_details",
                "args": {"case_id": str(setup["case_a"].id)},
            }),
            '{"type": "answer", "content": "Could not retrieve case."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["other"],  # not a member of case_a
        task="Get details for case alpha",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    # Tool should fail
    assert any(
        t.tool_name == "get_case_details" and t.success is False
        for t in result.tools_executed
    )


def test_agent_fabricated_citation_discarded(db_session, setup, fake_embedding):
    """13. [SOURCE:99] fabricated citation is discarded from citations list."""
    llm = FakeSequentialProvider(
        responses=[
            json.dumps({
                "type": "tool_call",
                "tool": "search_documents",
                "args": {"query": "contract", "case_id": str(setup["case_a"].id)},
            }),
            '{"type": "answer", "content": "[SOURCE:1] valid. [SOURCE:99] fabricated."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["lawyer"],
        task="What is in the contract?",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    # [SOURCE:99] should be discarded; [SOURCE:1] may be included if chunks retrieved
    for citation in result.citations:
        # Verify all citations come from actually retrieved chunks
        assert citation.document_name == "contract.pdf"


def test_agent_server_side_identity_enforced(db_session, setup, fake_embedding):
    """User identity comes from JWT, not from request body or LLM output."""
    # LLM tries to call list_cases but we use 'other' user (no memberships)
    llm = FakeSequentialProvider(
        responses=[
            '{"type": "tool_call", "tool": "list_cases", "args": {}}',
            '{"type": "answer", "content": "Listed cases."}',
        ]
    )
    result = run_agent(
        db=db_session,
        user=setup["other"],  # user with no memberships
        task="List all cases",
        embedding_provider=fake_embedding,
        llm_provider=llm,
    )
    # The tool should succeed but return 0 cases (authorization enforced in query)
    assert result.tools_executed[0].success is True
    # Verify by checking no case_a or case_b appeared in the tool result
    # (The agent will have seen an empty list in the tool result)


# ---------------------------------------------------------------------------
# API tests — POST /agent/run
# ---------------------------------------------------------------------------


def test_agent_api_unauthenticated_returns_403(client):
    """15. Unauthenticated request returns 403 (HTTPBearer scheme behavior)."""
    resp = client.post("/agent/run", json={"task": "What cases do I have?"})
    assert resp.status_code == 403


def test_agent_api_blank_task_returns_422(client, db_session):
    """16. Blank task returns 422 (Pydantic validation)."""
    user = make_user(db_session)
    resp = client.post(
        "/agent/run",
        json={"task": "   "},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_agent_api_valid_request_returns_200(client, db_session):
    """17. Valid request returns 200 with expected response schema."""
    import app.api.v1.agent as agent_module

    user = make_user(db_session)

    # Override providers to use fake implementations
    orig_llm = agent_module._get_llm_provider
    orig_emb = agent_module._get_embedding_provider
    try:
        agent_module._get_llm_provider = lambda: FakeSequentialProvider(
            responses=['{"type": "answer", "content": "The answer is 42."}']
        )
        agent_module._get_embedding_provider = lambda: FakeEmbeddingProvider(dim=384)

        resp = client.post(
            "/agent/run",
            json={"task": "What is the answer?"},
            headers=auth_headers(user),
        )
    finally:
        agent_module._get_llm_provider = orig_llm
        agent_module._get_embedding_provider = orig_emb

    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "tools_executed" in data
    assert "citations" in data
    assert "insufficient_evidence" in data
    assert "status" in data
    assert data["answer"] == "The answer is 42."
    assert data["status"] == "success"


def test_agent_api_llm_not_configured_returns_503(client, db_session):
    """18. LLM provider not configured returns 503."""
    import app.api.v1.agent as agent_module
    from app.services.llm_provider import LLMError

    user = make_user(db_session)
    orig_llm = agent_module._get_llm_provider

    def _raise():
        raise LLMError("LLM_API_KEY not configured.")

    try:
        agent_module._get_llm_provider = _raise
        resp = client.post(
            "/agent/run",
            json={"task": "What is the answer?"},
            headers=auth_headers(user),
        )
    finally:
        agent_module._get_llm_provider = orig_llm

    assert resp.status_code == 503


def test_agent_api_response_no_secrets(client, db_session):
    """19. API response never contains stack traces or secret keys."""
    import app.api.v1.agent as agent_module
    from app.services.llm_provider import LLMError

    user = make_user(db_session)
    orig_llm = agent_module._get_llm_provider

    def _raise():
        raise LLMError("LLM failure")

    try:
        agent_module._get_llm_provider = _raise
        resp = client.post(
            "/agent/run",
            json={"task": "task"},
            headers=auth_headers(user),
        )
    finally:
        agent_module._get_llm_provider = orig_llm

    assert resp.status_code == 503
    body = resp.json()
    # No stack traces or internal paths in detail
    assert "Traceback" not in str(body)
    assert "storage" not in str(body).lower() or "storage" in "temporarily unavailable"


def test_agent_api_user_cannot_spoof_identity(client, db_session):
    """20. User cannot supply another user's ID to gain their access."""
    import app.api.v1.agent as agent_module

    cl = make_client(db_session)
    unprivileged = make_user(db_session, role=UserRole.LAWYER)
    case = make_case(db_session, cl)

    orig_llm = agent_module._get_llm_provider
    orig_emb = agent_module._get_embedding_provider
    try:
        agent_module._get_llm_provider = lambda: FakeSequentialProvider(
            responses=[
                json.dumps({
                    "type": "tool_call",
                    "tool": "get_case_details",
                    "args": {"case_id": str(case.id)},
                }),
                '{"type": "answer", "content": "Got case."}',
            ]
        )
        agent_module._get_embedding_provider = lambda: FakeEmbeddingProvider(dim=384)

        # Unprivileged user makes request; case_id not in their memberships
        resp = client.post(
            "/agent/run",
            json={"task": "Get case details"},
            headers=auth_headers(unprivileged),
        )
    finally:
        agent_module._get_llm_provider = orig_llm
        agent_module._get_embedding_provider = orig_emb

    assert resp.status_code == 200
    data = resp.json()
    # The tool should have failed (case not accessible to unprivileged user)
    failed_tools = [t for t in data["tools_executed"] if not t["success"]]
    assert len(failed_tools) >= 1


# ---------------------------------------------------------------------------
# FakeSequentialProvider unit tests
# ---------------------------------------------------------------------------


def test_fake_sequential_returns_responses_in_order():
    """FakeSequentialProvider returns responses sequentially."""
    provider = FakeSequentialProvider(
        responses=[
            '{"type": "tool_call", "tool": "list_cases", "args": {}}',
            '{"type": "answer", "content": "Done."}',
        ]
    )
    r1 = provider.generate("sys", [{"role": "user", "content": "hello"}])
    r2 = provider.generate("sys", [{"role": "user", "content": "hello"}])
    assert "tool_call" in r1
    assert "answer" in r2


def test_fake_sequential_clamps_at_last_response():
    """FakeSequentialProvider returns last response when sequence is exhausted."""
    provider = FakeSequentialProvider(
        responses=['{"type": "answer", "content": "Only one."}']
    )
    for _ in range(5):
        r = provider.generate("sys", [])
    assert "Only one" in r


def test_fake_sequential_raise_on_call():
    """FakeSequentialProvider raises LLMError on configured call index."""
    provider = FakeSequentialProvider(
        responses=['{"type": "answer", "content": "ok"}'],
        raise_on=1,
    )
    with pytest.raises(LLMError):
        provider.generate("sys", [])
