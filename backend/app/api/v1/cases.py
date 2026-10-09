"""
Case and case-membership routes.

CASES
POST   /cases                              — create a case (ADMIN or LAWYER)
GET    /cases                              — list accessible cases
GET    /cases/{case_id}                    — get one case (membership-scoped)
PUT    /cases/{case_id}                    — update a case (ADMIN/OWNER/MEMBER)
DELETE /cases/{case_id}                    — delete a case (ADMIN or OWNER)

CASE MEMBERS
POST   /cases/{case_id}/members            — add a member (ADMIN or OWNER)
GET    /cases/{case_id}/members            — list members (any case member)
PUT    /cases/{case_id}/members/{user_id}  — change member role (ADMIN or OWNER)
DELETE /cases/{case_id}/members/{user_id}  — remove a member (ADMIN or OWNER)

Authorization invariant:
  Authorization is checked before resource access on every route.
  Non-members receive 404 (hides existence) rather than 403.
  Role violations (VIEWER attempting edit) receive 403.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    get_authorized_case,
    get_current_user,
    get_db,
    require_case_role,
    require_role,
)
from app.models.case import Case
from app.models.case_membership import CaseMemberRole, CaseMembership
from app.models.user import User, UserRole
from app.schemas.case import CaseCreate, CaseResponse, CaseUpdate
from app.schemas.case_membership import (
    CaseMembershipCreate,
    CaseMembershipResponse,
    CaseMembershipUpdate,
)
from app.services.case import (
    create_case,
    delete_case,
    list_cases_for_user,
    update_case,
)

router = APIRouter(prefix="/cases", tags=["cases"])


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_case_route(
    req: CaseCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.LAWYER)),
    ],
) -> CaseResponse:
    """
    Create a case.

    ADMIN and LAWYER may create cases. RESTRICTED_LAWYER is forbidden.

    When a LAWYER creates a case, they are automatically assigned as OWNER.
    ADMIN users are not assigned a membership (they have global access).
    """
    from app.models.client import Client

    client = db.get(Client, req.client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    try:
        case = create_case(db, req, created_by=current_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A case with this case_number already exists",
        )
    return CaseResponse.model_validate(case)


@router.get("", response_model=list[CaseResponse])
def list_cases_route(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[CaseResponse]:
    """
    List cases the current user is authorized to see.

    ADMIN: all cases.
    Others: only cases where the user holds a CaseMembership.

    Authorization is encoded in the database query — never post-fetch filtering.
    """
    cases = list_cases_for_user(db, current_user)
    return [CaseResponse.model_validate(c) for c in cases]


@router.get("/{case_id}", response_model=CaseResponse)
def get_case_route(
    case: Annotated[Case, Depends(get_authorized_case)],
) -> CaseResponse:
    """Return one case. Non-members receive 404 (hides existence)."""
    return CaseResponse.model_validate(case)


@router.put("/{case_id}", response_model=CaseResponse)
def update_case_route(
    req: CaseUpdate,
    case: Annotated[
        Case,
        Depends(require_case_role(CaseMemberRole.OWNER, CaseMemberRole.MEMBER)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> CaseResponse:
    """
    Update a case.

    ADMIN: always allowed.
    OWNER or MEMBER: allowed.
    VIEWER: 403.
    Non-member: 404.
    """
    return CaseResponse.model_validate(update_case(db, case, req))


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case_route(
    case: Annotated[Case, Depends(require_case_role(CaseMemberRole.OWNER))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Delete a case. ADMIN or OWNER only.

    Cascade: memberships are deleted automatically (SQLAlchemy cascade).
    """
    delete_case(db, case)


# ---------------------------------------------------------------------------
# Case members
# ---------------------------------------------------------------------------


@router.post(
    "/{case_id}/members",
    response_model=CaseMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member_route(
    case_id: uuid.UUID,
    req: CaseMembershipCreate,
    case: Annotated[Case, Depends(require_case_role(CaseMemberRole.OWNER))],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CaseMembershipResponse:
    """
    Add a user to a case. ADMIN or OWNER only.

    Returns 409 if the user is already a member.
    Returns 404 if the target user does not exist.
    """
    target_user = db.get(User, req.user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    membership = CaseMembership(
        case_id=case_id,
        user_id=req.user_id,
        role=req.role,
    )
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this case",
        )
    db.refresh(membership)
    return CaseMembershipResponse.model_validate(membership)


@router.get("/{case_id}/members", response_model=list[CaseMembershipResponse])
def list_members_route(
    case: Annotated[Case, Depends(get_authorized_case)],
) -> list[CaseMembershipResponse]:
    """List members of a case. Any case member (any role) may view the list."""
    return [CaseMembershipResponse.model_validate(m) for m in case.memberships]


@router.put(
    "/{case_id}/members/{user_id}",
    response_model=CaseMembershipResponse,
)
def update_member_role_route(
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    req: CaseMembershipUpdate,
    case: Annotated[Case, Depends(require_case_role(CaseMemberRole.OWNER))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseMembershipResponse:
    """
    Change a member's case role. ADMIN or OWNER only.

    Returns 404 if the target user is not a member.
    """
    membership = (
        db.query(CaseMembership)
        .filter(
            CaseMembership.case_id == case_id,
            CaseMembership.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )
    membership.role = req.role
    db.commit()
    db.refresh(membership)
    return CaseMembershipResponse.model_validate(membership)


@router.delete(
    "/{case_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member_route(
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    case: Annotated[Case, Depends(require_case_role(CaseMemberRole.OWNER))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Remove a member from a case. ADMIN or OWNER only.

    Returns 404 if the target user is not a member.
    Returns 400 if removing this user would leave the case without an OWNER.
    """
    membership = (
        db.query(CaseMembership)
        .filter(
            CaseMembership.case_id == case_id,
            CaseMembership.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Membership not found",
        )
    if membership.role == CaseMemberRole.OWNER:
        owner_count = (
            db.query(CaseMembership)
            .filter(
                CaseMembership.case_id == case_id,
                CaseMembership.role == CaseMemberRole.OWNER,
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last owner of a case. "
                "Assign another owner first.",
            )
    db.delete(membership)
    db.commit()
