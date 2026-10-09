"""
Client routes.

POST   /clients              — create a client (ADMIN or LAWYER)
GET    /clients              — list accessible clients
GET    /clients/{client_id}  — get one client (membership-scoped)
PUT    /clients/{client_id}  — update a client (ADMIN or LAWYER with case access)
DELETE /clients/{client_id}  — delete a client (ADMIN only)

Authorization principle: resource access is determined at query time.
Non-admin users see only clients reachable through their case memberships.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_role
from app.models.client import Client
from app.models.user import User, UserRole
from app.schemas.client import ClientCreate, ClientResponse, ClientUpdate
from app.services.client import (
    can_modify_client,
    create_client,
    delete_client,
    get_client_for_user,
    list_clients_for_user,
    update_client,
)

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post(
    "",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_client_route(
    req: ClientCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.LAWYER)),
    ],
) -> ClientResponse:
    """
    Create a new client.

    ADMIN and LAWYER may create clients.
    RESTRICTED_LAWYER is forbidden (system role does not permit client creation).
    """
    return ClientResponse.model_validate(create_client(db, req))


@router.get("", response_model=list[ClientResponse])
def list_clients_route(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ClientResponse]:
    """
    List clients the current user is authorized to see.

    ADMIN: all clients.
    Others: only clients reachable through their case memberships.

    Authorization is encoded in the database query — never post-fetch filtering.
    """
    clients = list_clients_for_user(db, current_user)
    return [ClientResponse.model_validate(c) for c in clients]


@router.get("/{client_id}", response_model=ClientResponse)
def get_client_route(
    client_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ClientResponse:
    """
    Return one client.

    Returns 404 for both non-existent and unauthorized clients (hides existence).
    """
    client = get_client_for_user(db, client_id, current_user)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    return ClientResponse.model_validate(client)


@router.put("/{client_id}", response_model=ClientResponse)
def update_client_route(
    client_id: uuid.UUID,
    req: ClientUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ClientResponse:
    """
    Update a client.

    ADMIN: always allowed.
    LAWYER: allowed only if they hold OWNER or MEMBER role in at least one
            case belonging to this client.
    RESTRICTED_LAWYER: forbidden (returns 403 on can_modify_client check).
    """
    client = get_client_for_user(db, client_id, current_user)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    if not can_modify_client(db, client_id, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to modify this client",
        )
    return ClientResponse.model_validate(update_client(db, client, req))


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client_route(
    client_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> None:
    """
    Delete a client. ADMIN only.

    Returns 409 if the client has associated cases (prevents accidental
    orphaning of case data).
    """
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    try:
        delete_client(db, client)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
