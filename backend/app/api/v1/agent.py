"""
AI agent endpoint — Day 7.

POST /agent/run
  Submit a task; receive a grounded answer with tool execution trace and citations.
  Requires authentication.

Authorization
-------------
  All requests require a valid JWT.  The authenticated user identity is never
  overridable by request body content.  Every tool call independently re-checks
  authorization.

Security
--------
  - API keys for LLM and embedding providers are never exposed.
  - Stack traces are never included in error responses.
  - Execution trace shows tool names and success status only (no raw args/results).
  - If LLM_API_KEY is not configured, returns HTTP 503.
  - If embedding service is not configured, returns HTTP 503.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.agent import (
    AgentCitation,
    AgentRunRequest,
    AgentRunResponse,
    AgentToolTrace,
)
from app.services.agent import AgentResult, run_agent
from app.services.llm_provider import LLMError
from app.services.rag import RagSource

router = APIRouter(prefix="/agent", tags=["agent"])


def _get_embedding_provider():
    from app.services.embedding import get_embedding_provider

    return get_embedding_provider()


def _get_llm_provider():
    from app.services.llm import get_llm_provider

    return get_llm_provider()


# ---------------------------------------------------------------------------
# POST /agent/run
# ---------------------------------------------------------------------------


@router.post("/run", response_model=AgentRunResponse)
def agent_run(
    body: AgentRunRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AgentRunResponse:
    """
    Run the AI agent on a legal-workflow task.

    The agent may call a controlled set of read-only tools (search_documents,
    list_cases, get_case_details, get_document_context) to gather authorized
    context before producing a final answer.

    Security guarantees:
    - The authenticated user identity comes exclusively from the JWT.
    - Every tool call independently re-verifies case-level access.
    - Unauthorized documents never enter the LLM context.
    - Tool names and arguments are validated server-side before execution.
    - The execution trace is concise (tool names + status only).

    DISCLAIMER: AI-generated answers may be incorrect.
    Always verify claims against the cited source documents.
    """
    try:
        embedding_provider = _get_embedding_provider()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service is temporarily unavailable.",
        )

    try:
        llm_provider = _get_llm_provider()
    except LLMError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI generation is temporarily unavailable. Please try again.",
        )

    try:
        result = run_agent(
            db=db,
            user=current_user,
            task=body.task,
            embedding_provider=embedding_provider,
            llm_provider=llm_provider,
            case_id=body.case_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except LLMError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI generation is temporarily unavailable. Please try again.",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="An error occurred. Please try again.",
        )

    return _to_response(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(result: AgentResult) -> AgentRunResponse:
    return AgentRunResponse(
        answer=result.answer,
        tools_executed=[
            AgentToolTrace(tool_name=t.tool_name, success=t.success)
            for t in result.tools_executed
        ],
        citations=[_to_agent_citation(c) for c in result.citations],
        insufficient_evidence=result.insufficient_evidence,
        status=result.status,
        error=result.error,
    )


def _to_agent_citation(src: RagSource) -> AgentCitation:
    return AgentCitation(
        document_id=src.document_id,
        document_name=src.document_name,
        case_id=src.case_id,
        chunk_id=src.chunk_id,
        chunk_index=src.chunk_index,
        page_number=src.page_number,
        excerpt=src.excerpt,
        similarity=src.similarity,
    )
