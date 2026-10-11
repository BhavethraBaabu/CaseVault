"""
Semantic search endpoint.

POST /search
  - Requires authentication.
  - Validates query (non-blank, ≤ 2000 chars) and limit (1–50).
  - If case_id is supplied, verifies the user has access before querying.
  - Authorization is enforced in the database query before similarity ranking
    and result limiting.  Global top-k retrieval followed by filtering is
    never used.
  - Returns ranked SearchResponse; never returns embedding vectors, storage
    paths, or unauthorised document names.

POST /search/embed  (ADMIN only)
  - Triggers batch embedding generation for all PENDING chunks.
  - Protected: only ADMIN may start an expensive bulk embed job.
  - Returns the count of newly embedded chunks.

Authorization model mirrors Day 3/4:
  ADMIN              — searches across all cases.
  OWNER/MEMBER/VIEWER — searches only their authorized cases.
  RESTRICTED_LAWYER  — same as above; access is membership-gated.
  Non-members        — receive zero results from unauthorised cases.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_role
from app.core.config import settings
from app.models.user import User, UserRole
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem
from app.services.embedding_provider import EmbeddingError
from app.services.search import semantic_search

router = APIRouter(tags=["search"])


def _get_provider():
    """
    Lazily import and return the process-level embedding provider.

    Import is deferred so that sentence-transformers is not loaded
    at application startup or during tests that override this dependency.
    """
    from app.services.embedding import get_embedding_provider

    return get_embedding_provider()


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


@router.post(
    "/search",
    response_model=SearchResponse,
)
def search_documents(
    body: SearchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SearchResponse:
    """
    Search document chunks semantically.

    The query is embedded on the server using the configured local model;
    no text is sent to an external API.

    If no document chunks have been embedded yet, returns an empty result
    with a helpful message.  Run POST /search/embed (ADMIN) to generate
    embeddings for existing documents.

    The similarity score is cosine similarity ∈ [0, 1].
    Higher = more relevant.

    Errors:
      422  — blank query, invalid limit, or unrecognised case_id.
      403  — case_id refers to a case the user cannot access.
      503  — embedding model could not be loaded.
    """
    # Validate limit against global maximum
    limit = min(body.limit, settings.search_max_limit)

    provider = _get_provider()

    try:
        results = semantic_search(
            db=db,
            user=current_user,
            query_text=body.query,
            provider=provider,
            case_id=body.case_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except EmbeddingError as exc:
        # Do not surface provider internals — return a safe 503
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service is temporarily unavailable. Please try again.",
        ) from exc
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search is temporarily unavailable. Please try again.",
        )

    items = [
        SearchResultItem(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_name=r.document_name,
            case_id=r.case_id,
            chunk_index=r.chunk_index,
            page_number=r.page_number,
            content=r.content,
            similarity=r.similarity,
        )
        for r in results
    ]

    return SearchResponse(
        query=body.query,
        results=items,
        total=len(items),
    )


# ---------------------------------------------------------------------------
# Admin: trigger batch embedding
# ---------------------------------------------------------------------------


@router.post(
    "/search/embed",
    status_code=status.HTTP_200_OK,
)
def trigger_embedding(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> dict:
    """
    Trigger embedding generation for all unembedded document chunks.

    ADMIN only.  Runs synchronously — do not call on large datasets without
    a background task queue.

    Returns:
        {"embedded": <count>}
    """
    from app.services.embedding import embed_pending_chunks

    provider = _get_provider()

    try:
        count = embed_pending_chunks(db, provider, batch_size=settings.embedding_batch_size)
    except EmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding service is temporarily unavailable.",
        ) from exc
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Embedding generation failed.",
        )

    return {"embedded": count}
