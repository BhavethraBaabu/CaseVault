import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.user import UserRole


class UserResponse(BaseModel):
    """
    Safe user representation returned by the API.
    Never includes password_hash or any sensitive credential.
    """

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
