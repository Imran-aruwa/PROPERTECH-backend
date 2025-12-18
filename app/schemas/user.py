from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional
from enum import Enum


class UserRoleEnum(str, Enum):
    ADMIN = "admin"
    OWNER = "owner"
    STAFF = "staff"
    TENANT = "tenant"
    AGENT = "agent"
    CARETAKER = "caretaker"


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str
    role: Optional[str] = "owner"
    fullName: Optional[str] = None  # Accept camelCase from frontend

    def get_full_name(self) -> str:
        return self.fullName or self.full_name or ""

    def get_role(self) -> str:
        role_value = (self.role or "owner").lower()
        valid_roles = ["admin", "owner", "staff", "tenant", "agent", "caretaker"]
        return role_value if role_value in valid_roles else "owner"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    id: UUID
    role: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None