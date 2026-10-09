import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.case import CaseStatus


class CaseCreate(BaseModel):
    client_id: uuid.UUID
    case_number: str
    title: str
    description: str | None = None
    status: CaseStatus = CaseStatus.OPEN

    @field_validator("case_number", "title")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class CaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: CaseStatus | None = None


class CaseResponse(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    case_number: str
    title: str
    description: str | None
    status: CaseStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
