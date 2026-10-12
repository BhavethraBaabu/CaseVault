"""
Agent tool registry — Day 7.

Implements four read-only tools that the AI agent may invoke.  Every tool
enforces authorization independently — the LLM cannot bypass permissions by
supplying a different user ID or omitting a case scope.

Security invariants
-------------------
1. Authorization is checked on every tool call, every invocation.
2. Unauthorized resources return "not found" (404-equivalent), never 403.
3. Tools are read-only; no mutations are allowed.
4. Storage paths, credentials, and internal IDs not in the result set are
   never returned.
5. Tool input is validated against explicit Pydantic schemas before execution.
6. The LLM cannot invoke arbitrary functions — only the four tools below.

Tools
-----
  search_documents      — semantic search over authorized document chunks
  list_cases            — list cases accessible to the authenticated user
  get_case_details      — retrieve metadata for a specific authorized case
  get_document_context  — retrieve text chunks from an authorized document
"""

import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_membership import CaseMembership
from app.models.document import Document, DocumentChunk
from app.models.user import User, UserRole
from app.services.case import list_cases_for_user
from app.services.embedding_provider import EmbeddingProvider
from app.services.search import SearchResult, semantic_search

# Maximum characters of a single chunk's content included in a tool result.
# Prevents context-window overflow from individual very long chunks.
_MAX_CHUNK_CHARS = 800


# ---------------------------------------------------------------------------
# ToolResult — returned by every tool execution function
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """
    Structured result returned by every tool execution function.

    success      — True if the tool completed without error.
    data         — Structured result dict (safe for LLM context).
    error        — Safe error message if success=False; no internals.
    raw_chunks   — SearchResult objects from search_documents, for citation
                   tracking.  Not serialised into LLM context directly.
    """

    success: bool
    data: dict
    error: str | None = None
    raw_chunks: list[SearchResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool A: search_documents
# ---------------------------------------------------------------------------

SEARCH_DOCUMENTS_NAME = "search_documents"
SEARCH_DOCUMENTS_DESCRIPTION = (
    "Search for relevant legal document excerpts matching a natural-language query. "
    "Only documents the authenticated user is authorized to access are searched. "
    "Returns ranked excerpts with source numbers for citation. "
    "Optional: restrict to a specific case by providing case_id."
)


class SearchDocumentsInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    case_id: uuid.UUID | None = None
    limit: int = Field(default=5, ge=1, le=10)


def execute_search_documents(
    db: Session,
    user: User,
    args: dict,
    embedding_provider: EmbeddingProvider,
    source_offset: int = 0,
) -> ToolResult:
    """
    Execute a permission-aware semantic search.

    source_offset: number of chunks already accumulated in this agent run,
    used to assign sequential source numbers across multiple search calls.

    Authorization: enforced inside semantic_search() via SQL JOIN/WHERE
    before ranking and limiting.  Non-member cases return zero results.
    """
    try:
        inp = SearchDocumentsInput.model_validate(args)
    except Exception as exc:
        return ToolResult(success=False, data={}, error=f"Invalid arguments: {exc}")

    try:
        results = semantic_search(
            db=db,
            user=user,
            query_text=inp.query,
            provider=embedding_provider,
            case_id=inp.case_id,
            limit=inp.limit,
        )
    except ValueError as exc:
        return ToolResult(success=False, data={}, error=str(exc))
    except Exception:
        return ToolResult(success=False, data={}, error="Search failed.")

    sources = []
    for i, r in enumerate(results):
        sources.append(
            {
                "source_number": source_offset + i + 1,
                "document_name": r.document_name,
                "case_id": str(r.case_id),
                "page_number": r.page_number,
                "content": r.content[:_MAX_CHUNK_CHARS],
            }
        )

    return ToolResult(
        success=True,
        data={"total": len(results), "sources": sources},
        raw_chunks=results,
    )


# ---------------------------------------------------------------------------
# Tool B: list_cases
# ---------------------------------------------------------------------------

LIST_CASES_NAME = "list_cases"
LIST_CASES_DESCRIPTION = (
    "List all legal cases the authenticated user is authorized to access. "
    "Returns case IDs, case numbers, titles, and statuses. "
    "No arguments required."
)


class ListCasesInput(BaseModel):
    pass


def execute_list_cases(
    db: Session,
    user: User,
    args: dict,
) -> ToolResult:
    """
    List cases authorized for the current user.

    Authorization: list_cases_for_user() encodes the SQL JOIN/WHERE
    constraint — ADMIN sees all, others see only member cases.
    The LLM cannot supply a different user identity.
    """
    # Validate args (no required fields, but reject unknown keys)
    try:
        ListCasesInput.model_validate(args)
    except Exception as exc:
        return ToolResult(success=False, data={}, error=f"Invalid arguments: {exc}")

    try:
        cases = list_cases_for_user(db, user)
    except Exception:
        return ToolResult(success=False, data={}, error="Failed to list cases.")

    return ToolResult(
        success=True,
        data={
            "cases": [
                {
                    "id": str(c.id),
                    "case_number": c.case_number,
                    "title": c.title,
                    "status": c.status,
                }
                for c in cases
            ],
            "total": len(cases),
        },
    )


# ---------------------------------------------------------------------------
# Tool C: get_case_details
# ---------------------------------------------------------------------------

GET_CASE_DETAILS_NAME = "get_case_details"
GET_CASE_DETAILS_DESCRIPTION = (
    "Retrieve metadata for a specific legal case by its ID. "
    "Returns case number, title, description, and status. "
    "Returns an error if the case does not exist or the user cannot access it."
)


class GetCaseDetailsInput(BaseModel):
    case_id: uuid.UUID


def execute_get_case_details(
    db: Session,
    user: User,
    args: dict,
) -> ToolResult:
    """
    Retrieve case metadata with per-call authorization.

    Authorization: ADMIN bypasses membership check; others require a
    CaseMembership record.  Returns "Case not found." for both nonexistent
    and unauthorized cases (resource-hiding).
    """
    try:
        inp = GetCaseDetailsInput.model_validate(args)
    except Exception as exc:
        return ToolResult(success=False, data={}, error=f"Invalid arguments: {exc}")

    if user.role == UserRole.ADMIN:
        case: Case | None = db.get(Case, inp.case_id)
    else:
        case = (
            db.query(Case)
            .join(CaseMembership, CaseMembership.case_id == Case.id)
            .filter(
                Case.id == inp.case_id,
                CaseMembership.user_id == user.id,
            )
            .first()
        )

    if case is None:
        return ToolResult(success=False, data={}, error="Case not found.")

    return ToolResult(
        success=True,
        data={
            "id": str(case.id),
            "case_number": case.case_number,
            "title": case.title,
            "description": case.description,
            "status": case.status,
        },
    )


# ---------------------------------------------------------------------------
# Tool D: get_document_context
# ---------------------------------------------------------------------------

GET_DOCUMENT_CONTEXT_NAME = "get_document_context"
GET_DOCUMENT_CONTEXT_DESCRIPTION = (
    "Retrieve text excerpts (chunks) from a specific document. "
    "Both document_id and case_id are required. "
    "The document must belong to the specified case. "
    "The user must be authorized to access the case. "
    "Returns the first N chunks from the document."
)


class GetDocumentContextInput(BaseModel):
    document_id: uuid.UUID
    case_id: uuid.UUID
    max_chunks: int = Field(default=3, ge=1, le=5)


def execute_get_document_context(
    db: Session,
    user: User,
    args: dict,
) -> ToolResult:
    """
    Retrieve document chunks with per-call authorization.

    Security:
    - Case access verified first; returns "not found" if unauthorized.
    - Document must belong to the stated case (prevents cross-case ID injection).
    - Storage paths and internal keys are never returned.
    """
    try:
        inp = GetDocumentContextInput.model_validate(args)
    except Exception as exc:
        return ToolResult(success=False, data={}, error=f"Invalid arguments: {exc}")

    # 1. Verify case access
    if user.role == UserRole.ADMIN:
        case: Case | None = db.get(Case, inp.case_id)
    else:
        case = (
            db.query(Case)
            .join(CaseMembership, CaseMembership.case_id == Case.id)
            .filter(
                Case.id == inp.case_id,
                CaseMembership.user_id == user.id,
            )
            .first()
        )

    if case is None:
        return ToolResult(success=False, data={}, error="Case not found.")

    # 2. Verify document belongs to the stated case
    doc: Document | None = (
        db.query(Document)
        .filter(
            Document.id == inp.document_id,
            Document.case_id == inp.case_id,  # Must match — prevents cross-case injection
        )
        .first()
    )
    if doc is None:
        return ToolResult(success=False, data={}, error="Document not found.")

    # 3. Retrieve chunks (ordered, bounded)
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
        .limit(inp.max_chunks)
        .all()
    )

    return ToolResult(
        success=True,
        data={
            "document_id": str(doc.id),
            "document_name": doc.original_filename,
            "case_id": str(doc.case_id),
            "status": doc.status,
            "chunks": [
                {
                    "chunk_index": c.chunk_index,
                    "page_number": c.page_number,
                    "content": c.content[:_MAX_CHUNK_CHARS],
                }
                for c in chunks
            ],
        },
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

#: Ordered list of all registered tool names (used for allowlisting).
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    [
        SEARCH_DOCUMENTS_NAME,
        LIST_CASES_NAME,
        GET_CASE_DETAILS_NAME,
        GET_DOCUMENT_CONTEXT_NAME,
    ]
)

#: Human-readable descriptions keyed by tool name, used to build the system prompt.
TOOL_DESCRIPTIONS: dict[str, str] = {
    SEARCH_DOCUMENTS_NAME: SEARCH_DOCUMENTS_DESCRIPTION,
    LIST_CASES_NAME: LIST_CASES_DESCRIPTION,
    GET_CASE_DETAILS_NAME: GET_CASE_DETAILS_DESCRIPTION,
    GET_DOCUMENT_CONTEXT_NAME: GET_DOCUMENT_CONTEXT_DESCRIPTION,
}

#: Tool argument schemas keyed by tool name, for inclusion in the system prompt.
TOOL_ARG_SCHEMAS: dict[str, str] = {
    SEARCH_DOCUMENTS_NAME: (
        '{"query": "<string, required>", '
        '"case_id": "<UUID string, optional>", '
        '"limit": <int 1-10, optional, default 5>}'
    ),
    LIST_CASES_NAME: "{} (no arguments)",
    GET_CASE_DETAILS_NAME: '{"case_id": "<UUID string, required>"}',
    GET_DOCUMENT_CONTEXT_NAME: (
        '{"document_id": "<UUID string, required>", '
        '"case_id": "<UUID string, required>", '
        '"max_chunks": <int 1-5, optional, default 3>}'
    ),
}
