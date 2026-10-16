"""
Day 9 observability tests.

Covers:
  - Request ID middleware: generation, propagation, validation, response header
  - Health endpoints: liveness, readiness (success + failure), config status
  - Global exception handlers: safe messages, request_id in error body
  - AI pipeline timing: structured log fields emitted after operations
  - Security: no credentials or document content in logs
  - Concurrent request independence: separate IDs per request
"""

import asyncio
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.deps import get_db
from app.core.request_context import (
    REQUEST_ID_HEADER,
    generate_request_id,
    get_request_id,
    is_safe_request_id,
    request_id_var,
)
from app.db.session import Base
from app.main import app as fastapi_app

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Request context unit tests
# ---------------------------------------------------------------------------


def test_get_request_id_default_outside_request():
    """get_request_id() returns '-' when called outside a request context."""
    assert get_request_id() == "-"


def test_generate_request_id_is_uuid():
    """generate_request_id() returns a valid UUID4 string."""
    rid = generate_request_id()
    parsed = uuid.UUID(rid, version=4)
    assert str(parsed) == rid


def test_is_safe_request_id_valid_uuid():
    rid = str(uuid.uuid4())
    assert is_safe_request_id(rid) is True


def test_is_safe_request_id_valid_alphanumeric():
    assert is_safe_request_id("abc-123-XYZ") is True


def test_is_safe_request_id_empty_string():
    assert is_safe_request_id("") is False


def test_is_safe_request_id_too_long():
    assert is_safe_request_id("a" * 65) is False


def test_is_safe_request_id_max_length_ok():
    assert is_safe_request_id("a" * 64) is True


def test_is_safe_request_id_rejects_newline():
    assert is_safe_request_id("abc\ndef") is False


def test_is_safe_request_id_rejects_semicolon():
    assert is_safe_request_id("abc;DROP TABLE") is False


def test_is_safe_request_id_rejects_space():
    assert is_safe_request_id("id with spaces") is False


def test_request_id_context_var_set_and_reset():
    """ContextVar is correctly set and reset."""
    token = request_id_var.set("test-id-123")
    assert get_request_id() == "test-id-123"
    request_id_var.reset(token)
    assert get_request_id() == "-"


# ---------------------------------------------------------------------------
# Request ID middleware — HTTP tests
# ---------------------------------------------------------------------------


def test_request_id_header_generated_when_absent(client):
    """Response includes X-Request-ID when none was supplied."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert REQUEST_ID_HEADER in response.headers


def test_generated_request_id_is_valid_uuid(client):
    """Generated X-Request-ID is a valid UUID4."""
    response = client.get("/health/live")
    rid = response.headers.get(REQUEST_ID_HEADER, "")
    parsed = uuid.UUID(rid, version=4)
    assert str(parsed) == rid


def test_valid_request_id_is_echoed(client):
    """A valid inbound X-Request-ID is returned unchanged."""
    custom_id = "my-custom-id-abc"
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: custom_id})
    assert response.headers.get(REQUEST_ID_HEADER) == custom_id


def test_invalid_request_id_is_replaced(client):
    """An invalid inbound X-Request-ID is replaced with a fresh UUID."""
    bad_id = "bad id with spaces; injection"
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: bad_id})
    returned_id = response.headers.get(REQUEST_ID_HEADER, "")
    # Must not echo the invalid value
    assert returned_id != bad_id
    # Must be a valid UUID4 instead
    parsed = uuid.UUID(returned_id, version=4)
    assert str(parsed) == returned_id


def test_oversized_request_id_is_replaced(client):
    """An X-Request-ID exceeding 64 chars is replaced with a fresh UUID."""
    long_id = "a" * 65
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: long_id})
    returned_id = response.headers.get(REQUEST_ID_HEADER, "")
    assert returned_id != long_id
    uuid.UUID(returned_id, version=4)  # must be a valid UUID


def test_different_requests_get_different_ids(client):
    """Two successive requests receive different X-Request-IDs."""
    r1 = client.get("/health/live")
    r2 = client.get("/health/live")
    assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]


def test_request_id_returned_on_error_response(client):
    """Error responses include X-Request-ID header."""
    # Trigger a 404 (unknown route)
    response = client.get("/does-not-exist")
    assert REQUEST_ID_HEADER in response.headers


def test_request_id_in_validation_error_body(client):
    """422 validation error body includes request_id field."""
    # POST /auth/login with missing fields triggers RequestValidationError
    response = client.post("/auth/login", json={})
    assert response.status_code == 422
    body = response.json()
    assert "request_id" in body


def test_validation_error_safe_message(client):
    """422 body contains the generic safe message, not raw field details."""
    response = client.post("/auth/login", json={})
    assert response.status_code == 422
    body = response.json()
    # Our handler returns a safe generic message
    assert body["detail"] == "Validation error."


# ---------------------------------------------------------------------------
# Concurrent requests — independent IDs
# ---------------------------------------------------------------------------


def test_concurrent_requests_have_independent_ids(client):
    """
    Two concurrent requests receive different, independent request IDs.

    Uses TestClient's synchronous interface via a thread pool to fire two
    requests simultaneously.
    """
    results = {}

    def fetch(key: str) -> None:
        # Each TestClient call is independent
        r = client.get("/health/live")
        results[key] = r.headers.get(REQUEST_ID_HEADER)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(fetch, "a")
        f2 = executor.submit(fetch, "b")
        f1.result()
        f2.result()

    assert results["a"] is not None
    assert results["b"] is not None
    assert results["a"] != results["b"]


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


def test_liveness_always_200(client):
    """GET /health/live always returns HTTP 200."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_shape(client):
    """GET /health/live response has exactly the expected fields."""
    response = client.get("/health/live")
    data = response.json()
    assert set(data.keys()) == {"status"}


def test_readiness_db_ok(client):
    """GET /health/ready returns 200 when database is reachable."""
    with patch("app.api.v1.health.check_db_ready", return_value=True):
        response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"]["database"] == "ok"


def test_readiness_db_unavailable(client):
    """GET /health/ready returns 503 when database is unreachable."""
    with patch("app.api.v1.health.check_db_ready", return_value=False):
        response = client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["database"] == "unavailable"


def test_readiness_db_exception(client):
    """GET /health/ready returns 503 safely when check raises an exception."""
    with patch(
        "app.api.v1.health.check_db_ready",
        side_effect=RuntimeError("connection refused"),
    ):
        response = client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    # Response must not include the exception message
    assert "connection refused" not in response.text


def test_readiness_no_credentials_in_response(client):
    """Readiness response never contains connection strings or credentials."""
    with patch("app.api.v1.health.check_db_ready", return_value=False):
        response = client.get("/health/ready")
    body_text = response.text
    assert "postgresql" not in body_text
    assert "password" not in body_text.lower()
    assert "casevault@" not in body_text


def test_config_status_returns_200(client):
    """GET /health/config always returns HTTP 200."""
    response = client.get("/health/config")
    assert response.status_code == 200


def test_config_status_shape(client):
    """GET /health/config response has expected fields."""
    response = client.get("/health/config")
    data = response.json()
    assert "status" in data
    assert "environment" in data
    assert "providers" in data
    assert "llm" in data["providers"]
    assert "embedding" in data["providers"]


def test_config_status_no_api_key_in_response(client):
    """GET /health/config never includes actual API key values."""
    with patch("app.core.config.settings.llm_api_key", "sk-secret-api-key"):
        response = client.get("/health/config")
    assert "sk-secret-api-key" not in response.text


def test_config_status_llm_not_configured_when_key_missing(client):
    """llm shows 'not_configured' when LLM_API_KEY is not set."""
    with patch("app.core.config.settings.llm_api_key", None):
        response = client.get("/health/config")
    assert response.json()["providers"]["llm"] == "not_configured"


def test_config_status_llm_configured_when_key_present(client):
    """llm shows 'configured' when LLM_API_KEY is set."""
    with patch("app.core.config.settings.llm_api_key", "sk-test-key"):
        response = client.get("/health/config")
    assert response.json()["providers"]["llm"] == "configured"


def test_config_status_does_not_call_llm_api(client):
    """GET /health/config does not make any LLM network calls."""
    with patch("app.services.llm.get_llm_provider") as mock_llm:
        response = client.get("/health/config")
    assert response.status_code == 200
    mock_llm.assert_not_called()


def test_legacy_health_backwards_compatible(client):
    """GET /health still returns the Day 1–8 response shape."""
    with patch("app.api.v1.health.check_db_connection", return_value=True):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"status", "version", "database"}
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# DB readiness with timeout (check_db_ready)
# ---------------------------------------------------------------------------


def test_check_db_ready_returns_false_on_timeout():
    """check_db_ready() returns False when check_db_connection hangs."""
    from app.db.session import check_db_ready

    def slow_check():
        time.sleep(10)
        return True  # pragma: no cover

    with patch("app.db.session.check_db_connection", side_effect=slow_check):
        result = check_db_ready(timeout_seconds=0.05)
    assert result is False


def test_check_db_ready_returns_true_on_success():
    from app.db.session import check_db_ready

    with patch("app.db.session.check_db_connection", return_value=True):
        assert check_db_ready(timeout_seconds=5.0) is True


def test_check_db_ready_returns_false_on_exception():
    from app.db.session import check_db_ready

    with patch(
        "app.db.session.check_db_connection",
        side_effect=Exception("db unavailable"),
    ):
        assert check_db_ready(timeout_seconds=5.0) is False


# ---------------------------------------------------------------------------
# Unexpected error handler — safe messages
#
# We test the exception handler function directly to avoid complications with
# Starlette's BaseHTTPMiddleware task-group exception wrapping in Python 3.13.
# Integration-level tests use existing routes patched to raise exceptions.
# ---------------------------------------------------------------------------


def test_unexpected_error_handler_returns_500():
    """_unexpected_exception_handler returns HTTP 500."""
    from app.main import _unexpected_exception_handler

    request = MagicMock()
    request.method = "GET"
    request.url.path = "/test"
    response = asyncio.run(
        _unexpected_exception_handler(request, RuntimeError("internal boom"))
    )
    assert response.status_code == 500


def test_unexpected_error_handler_safe_message():
    """_unexpected_exception_handler returns generic detail, no internals."""
    from app.main import _unexpected_exception_handler

    request = MagicMock()
    request.method = "GET"
    request.url.path = "/test"
    response = asyncio.run(
        _unexpected_exception_handler(
            request, RuntimeError("super secret internal path /var/app/secrets.json")
        )
    )
    body = json.loads(response.body)
    assert body["detail"] == "Internal server error."
    assert "super secret" not in response.body.decode()
    assert "/var/app" not in response.body.decode()
    assert "Traceback" not in response.body.decode()


def test_unexpected_error_handler_includes_request_id():
    """_unexpected_exception_handler includes request_id in the body."""
    from app.main import _unexpected_exception_handler

    request = MagicMock()
    request.method = "GET"
    request.url.path = "/test"
    response = asyncio.run(
        _unexpected_exception_handler(request, ValueError("boom"))
    )
    body = json.loads(response.body)
    assert "request_id" in body


def test_unexpected_error_handler_echoes_active_request_id():
    """_unexpected_exception_handler echoes the active ContextVar request_id."""
    from app.main import _unexpected_exception_handler

    custom_id = "my-trace-id-99"
    token = request_id_var.set(custom_id)
    try:
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/test"
        response = asyncio.run(
            _unexpected_exception_handler(request, ValueError("boom"))
        )
        body = json.loads(response.body)
        assert body.get("request_id") == custom_id
    finally:
        request_id_var.reset(token)


def test_unexpected_error_handler_function_does_not_expose_exception_detail():
    """_unexpected_exception_handler never exposes the raw exception message."""
    from app.main import _unexpected_exception_handler

    secret_message = "SECRET_DB_CONN_STRING_postgres://user:pass@host/db"
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/test"
    response = asyncio.run(
        _unexpected_exception_handler(request, RuntimeError(secret_message))
    )
    body_str = response.body.decode()
    assert secret_message not in body_str
    assert "Internal server error." in body_str


# ---------------------------------------------------------------------------
# AI pipeline timing — structured log assertions
# ---------------------------------------------------------------------------


def test_semantic_search_emits_timing_log(db_session, caplog):
    """semantic_search logs duration_ms and results_count."""
    import logging

    from app.services.embedding import FakeEmbeddingProvider
    from app.services.search import semantic_search
    from tests.helpers import make_user

    user = make_user(db_session)

    provider = FakeEmbeddingProvider()

    with caplog.at_level(logging.INFO, logger="app.services.search"):
        semantic_search(
            db=db_session,
            user=user,
            query_text="contract terms",
            provider=provider,
            limit=5,
        )

    log_messages = [r.message for r in caplog.records]
    assert any("semantic_search" in m for m in log_messages)

    # Check structured extra fields are present on the record
    search_records = [
        r for r in caplog.records if "semantic_search" in r.message
    ]
    assert search_records, "No semantic_search log record found"
    rec = search_records[0]
    assert hasattr(rec, "duration_ms")
    assert isinstance(rec.duration_ms, float)
    assert hasattr(rec, "results_count")


def test_semantic_search_does_not_log_query_text(db_session, caplog):
    """semantic_search must not log the raw query string."""
    import logging

    from app.services.embedding import FakeEmbeddingProvider
    from app.services.search import semantic_search
    from tests.helpers import make_user

    secret_query = "SUPER_SECRET_SEARCH_TERM_DO_NOT_LOG"
    user = make_user(db_session)
    provider = FakeEmbeddingProvider()

    with caplog.at_level(logging.DEBUG, logger="app.services.search"):
        semantic_search(
            db=db_session,
            user=user,
            query_text=secret_query,
            provider=provider,
        )

    all_text = " ".join(r.getMessage() for r in caplog.records)
    assert secret_query not in all_text


def test_rag_ask_emits_timing_log(db_session, caplog):
    """rag.ask logs operation, duration_ms, and llm_called."""
    import logging

    from app.services.embedding import FakeEmbeddingProvider
    from app.services.llm_provider import FakeLLMProvider
    from app.services.rag import ask
    from tests.helpers import make_user

    user = make_user(db_session)
    provider = FakeEmbeddingProvider()
    llm = FakeLLMProvider()

    with caplog.at_level(logging.INFO, logger="app.services.rag"):
        ask(
            db=db_session,
            user=user,
            question="What are the contract terms?",
            embedding_provider=provider,
            llm_provider=llm,
        )

    rag_records = [r for r in caplog.records if "rag.ask" in r.message]
    assert rag_records, "No rag.ask log record found"
    rec = rag_records[0]
    assert hasattr(rec, "duration_ms")
    assert hasattr(rec, "llm_called")
    assert hasattr(rec, "insufficient_evidence")


def test_rag_ask_does_not_log_question_text(db_session, caplog):
    """rag.ask must not log the user's question or document content."""
    import logging

    from app.services.embedding import FakeEmbeddingProvider
    from app.services.llm_provider import FakeLLMProvider
    from app.services.rag import ask
    from tests.helpers import make_user

    secret_question = "CONFIDENTIAL_QUESTION_TEXT_9999"
    user = make_user(db_session)
    provider = FakeEmbeddingProvider()
    llm = FakeLLMProvider()

    with caplog.at_level(logging.DEBUG, logger="app.services.rag"):
        ask(
            db=db_session,
            user=user,
            question=secret_question,
            embedding_provider=provider,
            llm_provider=llm,
        )

    all_text = " ".join(r.getMessage() for r in caplog.records)
    assert secret_question not in all_text


def test_agent_run_emits_timing_log(db_session, caplog):
    """run_agent logs operation, duration_ms, and tool_calls."""
    import logging

    from app.services.agent import run_agent
    from app.services.embedding import FakeEmbeddingProvider
    from app.services.llm_provider import FakeSequentialProvider
    from tests.helpers import make_user

    user = make_user(db_session)
    provider = FakeEmbeddingProvider()
    llm = FakeSequentialProvider(
        responses=['{"type": "answer", "content": "No relevant docs found."}']
    )

    with caplog.at_level(logging.INFO, logger="app.services.agent"):
        run_agent(
            db=db_session,
            user=user,
            task="Summarize all cases",
            embedding_provider=provider,
            llm_provider=llm,
        )

    agent_records = [r for r in caplog.records if "agent.run" in r.message]
    assert agent_records, "No agent.run log record found"
    rec = agent_records[0]
    assert hasattr(rec, "duration_ms")
    assert hasattr(rec, "tool_calls")
    assert hasattr(rec, "outcome")


def test_agent_tool_call_count_in_log(db_session, caplog):
    """agent.run log record reflects the actual number of tool calls made."""
    import logging

    from app.services.agent import run_agent
    from app.services.embedding import FakeEmbeddingProvider
    from app.services.llm_provider import FakeSequentialProvider
    from tests.helpers import make_user

    user = make_user(db_session)
    provider = FakeEmbeddingProvider()
    llm = FakeSequentialProvider(
        responses=[
            '{"type": "tool_call", "tool": "list_cases", "args": {}}',
            '{"type": "answer", "content": "No cases found."}',
        ]
    )

    with caplog.at_level(logging.INFO, logger="app.services.agent"):
        run_agent(
            db=db_session,
            user=user,
            task="List my cases",
            embedding_provider=provider,
            llm_provider=llm,
        )

    agent_records = [r for r in caplog.records if "agent.run" in r.message]
    assert agent_records
    rec = agent_records[-1]
    # list_cases was called once
    assert rec.tool_calls >= 1


def test_document_ingest_emits_timing_log(db_session, caplog):
    """ingest_document logs operation, duration_ms, and chunk_count."""
    import logging
    import uuid

    from app.services.document import ingest_document

    txt_content = b"This is a simple legal document with contract terms and conditions."
    filename = "test_contract.txt"
    case_id = uuid.uuid4()
    user_id = uuid.uuid4()

    with caplog.at_level(logging.INFO, logger="app.services.document"):
        ingest_document(
            db=db_session,
            case_id=case_id,
            uploaded_by_id=user_id,
            filename=filename,
            content=txt_content,
        )

    ingest_records = [
        r for r in caplog.records if "document.ingest" in r.message
    ]
    assert ingest_records, "No document.ingest log record found"
    rec = ingest_records[0]
    assert hasattr(rec, "duration_ms")
    assert hasattr(rec, "file_size_bytes")
    assert hasattr(rec, "status")


def test_document_ingest_does_not_log_file_content(db_session, caplog):
    """ingest_document must not log raw document text."""
    import logging
    import uuid

    from app.services.document import ingest_document

    secret_content = b"CONFIDENTIAL_DOCUMENT_BODY_DO_NOT_LOG_ABCXYZ"
    case_id = uuid.uuid4()
    user_id = uuid.uuid4()

    with caplog.at_level(logging.DEBUG, logger="app.services.document"):
        ingest_document(
            db=db_session,
            case_id=case_id,
            uploaded_by_id=user_id,
            filename="secret.txt",
            content=secret_content,
        )

    all_text = " ".join(r.getMessage() for r in caplog.records)
    assert b"CONFIDENTIAL_DOCUMENT_BODY_DO_NOT_LOG_ABCXYZ".decode() not in all_text


# ---------------------------------------------------------------------------
# Security: no credentials in logs
# ---------------------------------------------------------------------------


def test_no_password_in_logs(client, caplog):
    """Login endpoint does not log the submitted password."""
    import logging

    secret_password = "SUPER_SECRET_PASSWORD_12345"

    with caplog.at_level(logging.DEBUG):
        client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": secret_password},
        )

    all_text = " ".join(r.getMessage() for r in caplog.records)
    assert secret_password not in all_text


def test_no_token_in_logs(client, caplog):
    """Authorization tokens are not logged."""
    import logging

    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.FAKE_SECRET_TOKEN"

    with caplog.at_level(logging.DEBUG):
        client.get("/auth/me", headers={"Authorization": f"Bearer {fake_token}"})

    all_text = " ".join(r.getMessage() for r in caplog.records)
    assert "FAKE_SECRET_TOKEN" not in all_text


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def test_configure_logging_sets_handler():
    """configure_logging() installs at least one handler on the root logger."""
    import logging

    from app.core.logging_config import configure_logging

    configure_logging(log_level="INFO")
    root = logging.getLogger()
    assert len(root.handlers) >= 1


def test_configure_logging_level_debug():
    """configure_logging() respects the DEBUG level argument."""
    import logging

    from app.core.logging_config import configure_logging

    configure_logging(log_level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    # Restore to INFO so other tests are not affected
    configure_logging(log_level="INFO")


def test_request_id_filter_injects_default(caplog):
    """_RequestIdFilter injects '-' when no request context is active."""
    import logging

    from app.core.logging_config import _RequestIdFilter

    flt = _RequestIdFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    flt.filter(record)
    assert record.request_id == "-"


def test_request_id_filter_injects_active_id(caplog):
    """_RequestIdFilter uses the active ContextVar value when set."""
    import logging

    from app.core.logging_config import _RequestIdFilter

    token = request_id_var.set("active-req-id")
    try:
        flt = _RequestIdFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        flt.filter(record)
        assert record.request_id == "active-req-id"
    finally:
        request_id_var.reset(token)
