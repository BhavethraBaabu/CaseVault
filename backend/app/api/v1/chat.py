"""
Chat (RAG) endpoints — Day 6.

POST /chat/ask
  Submit a question; get a grounded answer with source citations.
  Requires authentication.  Supports optional conversation_id (history)
  and case_id (scope).

GET  /chat/conversations
  List the current user's conversations.

GET  /chat/conversations/{conversation_id}/messages
  Return all messages in a conversation (owner only).

DELETE /chat/conversations/{conversation_id}
  Delete a conversation and its messages (owner only).

Authorization
-------------
  All endpoints require a valid JWT.  Conversation access is restricted to
  the owner; ADMIN may also access any conversation.  Case scopes are
  re-verified on every /chat/ask call.

Security
--------
  - API keys for the LLM provider are never exposed via these endpoints.
  - Stack traces are never included in error responses.
  - If LLM_API_KEY is not configured, /chat/ask returns HTTP 503.
  - Conversation ownership is verified before history is read or written.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.conversation import Conversation
from app.models.user import User, UserRole
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    ConversationResponse,
    MessageResponse,
    SourceCitation,
)
from app.services.llm_provider import LLMError
from app.services.rag import RagSource, ask

router = APIRouter(prefix="/chat", tags=["chat"])


def _get_embedding_provider():
    from app.services.embedding import get_embedding_provider

    return get_embedding_provider()


def _get_llm_provider():
    from app.services.llm import get_llm_provider

    return get_llm_provider()


# ---------------------------------------------------------------------------
# Ask — RAG question answering
# ---------------------------------------------------------------------------


@router.post("/ask", response_model=AskResponse)
def ask_question(
    body: AskRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AskResponse:
    """
    Submit a question and receive a grounded AI answer with citations.

    The answer is derived exclusively from document chunks the current user
    is authorized to access.  Source citations are validated server-side;
    the model cannot inject unauthorized references.

    If no relevant evidence is found, the response returns
    insufficient_evidence=true and a helpful message.

    If the LLM provider is not configured, returns HTTP 503.

    DISCLAIMER: AI-generated answers may be incorrect.  Verify claims
    against the cited source documents.
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
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    try:
        result = ask(
            db=db,
            user=current_user,
            question=body.question,
            embedding_provider=embedding_provider,
            llm_provider=llm_provider,
            conversation_id=body.conversation_id,
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

    return AskResponse(
        conversation_id=result.conversation_id,
        answer=result.answer,
        insufficient_evidence=result.insufficient_evidence,
        sources=[_to_source_citation(s) for s in result.sources],
    )


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ConversationResponse]:
    """
    Return the current user's conversations, newest first.

    ADMINs see all conversations.
    """
    q = db.query(Conversation)
    if current_user.role != UserRole.ADMIN:
        q = q.filter(Conversation.user_id == current_user.id)
    convs = q.order_by(Conversation.updated_at.desc()).all()
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
def get_messages(
    conversation_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[MessageResponse]:
    """
    Return all messages in a conversation.

    Returns HTTP 404 if the conversation does not exist or the current
    user is not the owner (resource-hiding).
    """
    conv = _get_authorized_conversation(db, current_user, conversation_id)
    return [MessageResponse.model_validate(m) for m in conv.messages]


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """
    Delete a conversation and all its messages.

    Owner or ADMIN only.  Returns 404 for non-owners to hide existence.
    """
    conv = _get_authorized_conversation(db, current_user, conversation_id)
    db.delete(conv)
    db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_authorized_conversation(
    db: Session,
    user: User,
    conversation_id: uuid.UUID,
) -> Conversation:
    """Return a Conversation if the user is the owner (or ADMIN), else 404."""
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    if user.role != UserRole.ADMIN and conv.user_id != user.id:
        # Resource-hiding: return 404 rather than 403
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conv


def _to_source_citation(src: RagSource) -> SourceCitation:
    return SourceCitation(
        document_id=src.document_id,
        document_name=src.document_name,
        case_id=src.case_id,
        chunk_id=src.chunk_id,
        chunk_index=src.chunk_index,
        page_number=src.page_number,
        excerpt=src.excerpt,
        similarity=src.similarity,
    )
