"""
Client service layer.

All list/get functions encode authorization directly in the SQL query.
Never fetch all records and filter in Python — authorization happens at
the database level.
"""
import uuid

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_membership import CaseMemberRole, CaseMembership
from app.models.client import Client
from app.models.user import User, UserRole
from app.schemas.client import ClientCreate, ClientUpdate


def create_client(db: Session, req: ClientCreate) -> Client:
    client = Client(**req.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def get_client_for_user(
    db: Session, client_id: uuid.UUID, user: User
) -> Client | None:
    """
    Return a client if the user is authorized to access it.

    Authorization is enforced in the SQL query:
    - ADMIN: can access any client
    - Others: can access a client only if they hold a CaseMembership
              in at least one of that client's cases
    """
    if user.role == UserRole.ADMIN:
        return db.get(Client, client_id)
    return (
        db.query(Client)
        .join(Case, Case.client_id == Client.id)
        .join(CaseMembership, CaseMembership.case_id == Case.id)
        .filter(Client.id == client_id, CaseMembership.user_id == user.id)
        .first()
    )


def list_clients_for_user(db: Session, user: User) -> list[Client]:
    """
    Return all clients the user is authorized to see.

    The authorized set is computed by the database via JOIN on case_memberships.
    Non-admin users receive only clients reachable through their memberships.
    """
    if user.role == UserRole.ADMIN:
        return db.query(Client).order_by(Client.name).all()
    return (
        db.query(Client)
        .join(Case, Case.client_id == Client.id)
        .join(CaseMembership, CaseMembership.case_id == Case.id)
        .filter(CaseMembership.user_id == user.id)
        .distinct()
        .order_by(Client.name)
        .all()
    )


def can_modify_client(db: Session, client_id: uuid.UUID, user: User) -> bool:
    """
    Check if the user has modify (write) permissions on a client.

    - ADMIN: always allowed
    - RESTRICTED_LAWYER: never allowed
    - LAWYER: allowed only if they hold OWNER or MEMBER role
              in at least one case belonging to this client
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.RESTRICTED_LAWYER:
        return False
    count = (
        db.query(CaseMembership)
        .join(Case, Case.id == CaseMembership.case_id)
        .filter(
            Case.client_id == client_id,
            CaseMembership.user_id == user.id,
            CaseMembership.role.in_([CaseMemberRole.OWNER, CaseMemberRole.MEMBER]),
        )
        .count()
    )
    return count > 0


def update_client(db: Session, client: Client, req: ClientUpdate) -> Client:
    data = req.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(client, key, value)
    db.commit()
    db.refresh(client)
    return client


def delete_client(db: Session, client: Client) -> None:
    """
    Delete a client.

    Raises ValueError if the client has associated cases, to prevent
    accidental orphaning of case data.
    """
    if client.cases:
        raise ValueError(
            "Cannot delete a client with associated cases. "
            "Archive or reassign all cases first."
        )
    db.delete(client)
    db.commit()
