import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from finql.auth.models import UserRole


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    branch_id: int | None
    is_active: bool
