import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.case_membership import CaseMemberRole


class CaseMembershipCreate(BaseModel):
    user_id: uuid.UUID
    role: CaseMemberRole = CaseMemberRole.MEMBER


class CaseMembershipUpdate(BaseModel):
    role: CaseMemberRole


class CaseMembershipResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    user_id: uuid.UUID
    role: CaseMemberRole
    created_at: datetime

    model_config = {"from_attributes": True}
