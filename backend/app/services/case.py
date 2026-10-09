"""
Case service layer.

All list/get functions encode authorization directly in the SQL query.
The critical invariant: authorization happens before resource retrieval,
not after.
"""

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_membership import CaseMemberRole, CaseMembership
from app.models.user import User, UserRole
from app.schemas.case import CaseCreate, CaseUpdate


def create_case(db: Session, req: CaseCreate, created_by: User) -> Case:
    """
    Create a case. If the creator is not ADMIN, automatically create
    a CaseMembership with role=OWNER so the creator owns the case.

    ADMIN users get global access and do not need a membership record.
    """
    case = Case(
        client_id=req.client_id,
        case_number=req.case_number,
        title=req.title,
        description=req.description,
        status=req.status,
    )
    db.add(case)
    db.flush()  # Assign case.id without committing

    if created_by.role != UserRole.ADMIN:
        membership = CaseMembership(
            case_id=case.id,
            user_id=created_by.id,
            role=CaseMemberRole.OWNER,
        )
        db.add(membership)

    db.commit()
    db.refresh(case)
    return case


def list_cases_for_user(db: Session, user: User) -> list[Case]:
    """
    Return all cases the user is authorized to see.

    Authorization is enforced in the SQL query:
    - ADMIN: all cases
    - Others: only cases where the user holds a CaseMembership

    This query is the security boundary — not application-layer filtering.
    """
    if user.role == UserRole.ADMIN:
        return db.query(Case).order_by(Case.case_number).all()
    return (
        db.query(Case)
        .join(CaseMembership, CaseMembership.case_id == Case.id)
        .filter(CaseMembership.user_id == user.id)
        .order_by(Case.case_number)
        .all()
    )


def update_case(db: Session, case: Case, req: CaseUpdate) -> Case:
    data = req.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(case, key, value)
    db.commit()
    db.refresh(case)
    return case


def delete_case(db: Session, case: Case) -> None:
    db.delete(case)
    db.commit()
