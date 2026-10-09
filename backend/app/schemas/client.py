import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class ClientCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    organization: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()


class ClientUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    organization: str | None = None


class ClientResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    organization: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
