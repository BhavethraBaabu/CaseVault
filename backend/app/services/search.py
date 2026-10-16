"""
Permission-aware semantic search service.

Critical security invariant
----------------------------
Authorization is applied INSIDE the database query BEFORE similarity ranking
and result limiting.  The system never:
  - Retrieves global top-k chunks and filters unauthorised ones afterward.
  - Trusts case_id or role values from the frontend without backend verification.
  - Returns embedding vectors, storage paths, or internal IDs not present in
    the authorised result set.

Authorization model
-------------------
  ADMIN              — may search across all cases (no membership required).
  OWNER/MEMBER/VIEWER — may search documents in assigned cases.
  RESTRICTED_LAWYER  — same as above (membership is explicit per case).
  Non-members        — receive zero results from unauthorised cases.

Query shape (PostgreSQL + pgvector)
------------------------------------
  Authenticated User
    → Authorized Case Memberships (JOIN or ADMIN bypass)
    → Documents (JOIN)
    → Chunks with non-null embedding (FILTER)
    → pgvector cosine distance ORDER BY
    → Top-K authorized results

SQLite fallback (unit tests)
-----------------------------
  When the database is SQLite (test environment), pgvector operators are
  unavailable.  The service falls back to Python-side cosine similarity
  computed over the authorized chunk set.  This fallback is NOT used in
  production and does NOT verify pgvector extension behaviour.
"""

import logging
import math
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.models.case_membership import CaseMembership
from app.models.document import Document, DocumentChunk
from app.models.user import User, UserRole
from app.services.embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single ranked search result."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    case_id: uuid.UUID
    chunk_index: int
    page_number: int | None
    content: str
    # Cosine similarity in [0, 1]; higher = more similar.
    # Derived from pgvector cosine DISTANCE: similarity = 1 - distance.
    similarity: float


def semantic_search(
    db: Session,
    user: User,
    query_text: str,
    provider: EmbeddingProvider,
    case_id: uuid.UUID | None = None,
    limit: int = 10,
) -> list[SearchResult]:
    """
    Execute a permission-aware semantic search.

    Args:
        db:         SQLAlchemy session.
        user:       Authenticated user (role is re-read from DB, not JWT).
        query_text: The search query (must be non-empty).
        provider:   Embedding provider used to vectorise the query.
        case_id:    If given, restrict search to this case.
                    The user must have access; raises ValueError if not.
        limit:      Maximum number of results to return.

    Returns:
        List of SearchResult ordered by descending similarity.
        Only chunks with an existing embedding are included.
        Never includes results from cases the user cannot access.

    Raises:
        ValueError for blank queries, invalid limits, or unauthorised case_id.
        EmbeddingError if the provider fails to embed the query.
    """
    query_text = query_text.strip()
    if not query_text:
        raise ValueError("Search query must not be empty.")
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    _t_start = time.perf_counter()

    # Generate query embedding — may raise EmbeddingError
    _t_embed = time.perf_counter()
    query_vector = provider.embed([query_text])[0]
    embed_ms = (time.perf_counter() - _t_embed) * 1000

    # Verify case access when case_id is supplied
    if case_id is not None:
        _verify_case_access(db, user, case_id)

    dialect_name = _dialect_name(db)
    if dialect_name == "postgresql":
        results = _search_postgresql(db, user, query_vector, case_id, limit)
    else:
        results = _search_python_fallback(db, user, query_vector, case_id, limit)

    total_ms = (time.perf_counter() - _t_start) * 1000
    logger.info(
        "semantic_search completed",
        extra={
            "operation": "semantic_search",
            "duration_ms": round(total_ms, 1),
            "embed_ms": round(embed_ms, 1),
            "results_count": len(results),
            "case_scoped": case_id is not None,
            "request_id": get_request_id(),
        },
    )
    return results


# ---------------------------------------------------------------------------
# PostgreSQL path (production)
# ---------------------------------------------------------------------------


def _search_postgresql(
    db: Session,
    user: User,
    query_vector: list[float],
    case_id: uuid.UUID | None,
    limit: int,
) -> list[SearchResult]:
    """
    Execute the search using pgvector cosine distance.

    Authorization is encoded in the JOIN/WHERE before ORDER BY + LIMIT.
    This guarantees that the TOP-K selection operates only on the
    authorized chunk set.
    """
    from pgvector.sqlalchemy import Vector  # type: ignore[import]

    query_array = query_vector  # pgvector handles list[float]

    q = (
        db.query(
            DocumentChunk,
            Document,
            DocumentChunk.embedding.op("<=>", return_type=Vector(len(query_vector)))(
                query_array
            ).label("distance"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(DocumentChunk.embedding.isnot(None))
    )

    if case_id is not None:
        q = q.filter(Document.case_id == case_id)

    if user.role != UserRole.ADMIN:
        q = q.join(
            CaseMembership,
            CaseMembership.case_id == Document.case_id,
        ).filter(CaseMembership.user_id == user.id)

    rows = q.order_by("distance").limit(limit).all()

    return [
        SearchResult(
            chunk_id=chunk.id,
            document_id=doc.id,
            document_name=doc.original_filename,
            case_id=doc.case_id,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            content=chunk.content,
            similarity=round(max(0.0, 1.0 - float(distance)), 6),
        )
        for chunk, doc, distance in rows
    ]


# ---------------------------------------------------------------------------
# SQLite fallback (unit tests only)
# ---------------------------------------------------------------------------


def _search_python_fallback(
    db: Session,
    user: User,
    query_vector: list[float],
    case_id: uuid.UUID | None,
    limit: int,
) -> list[SearchResult]:
    """
    Python-side cosine similarity fallback for SQLite (test databases).

    Fetches all authorized chunks with embeddings and computes cosine
    similarity in Python.  Authorization is enforced via the SQL WHERE
    clause before loading chunks.

    NOTE: This path is intentionally only used in tests.  It does NOT
    verify pgvector behaviour, index usage, or migration correctness.
    """
    q = (
        db.query(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(DocumentChunk.embedding.isnot(None))
    )

    if case_id is not None:
        q = q.filter(Document.case_id == case_id)

    if user.role != UserRole.ADMIN:
        q = q.join(
            CaseMembership,
            CaseMembership.case_id == Document.case_id,
        ).filter(CaseMembership.user_id == user.id)

    rows = q.all()

    if not rows:
        return []

    scored = []
    for chunk, doc in rows:
        if chunk.embedding is None:
            continue
        sim = _cosine_similarity(query_vector, chunk.embedding)
        scored.append(
            SearchResult(
                chunk_id=chunk.id,
                document_id=doc.id,
                document_name=doc.original_filename,
                case_id=doc.case_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                content=chunk.content,
                similarity=round(sim, 6),
            )
        )

    scored.sort(key=lambda r: r.similarity, reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity in [−1, 1]; clipped to [0, 1]."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _verify_case_access(db: Session, user: User, case_id: uuid.UUID) -> None:
    """
    Raise ValueError if the user cannot access the given case.

    ADMINs pass unconditionally.
    Others require a CaseMembership record.
    """
    if user.role == UserRole.ADMIN:
        return
    membership = (
        db.query(CaseMembership)
        .filter(
            CaseMembership.case_id == case_id,
            CaseMembership.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        raise ValueError("Case not found or access denied.")


def _dialect_name(db: Session) -> str:
    """Return the database dialect name from a SQLAlchemy session."""
    try:
        return db.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        return "unknown"
