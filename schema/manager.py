from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr


class ManagerCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class ManagerUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class PasswordUpdate(BaseModel):
    password: str


class ManagerResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
