from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("login")
    @classmethod
    def trim_login(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Required")
        return value


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    role: Literal["master", "worker", "manager", "admin"]
    specialty: str | None
    grade: int | None
    brigade_id: UUID | None
    shift_id: UUID | None


class AuthResponse(BaseModel):
    user: UserView
    csrf_token: str


class CsrfResponse(BaseModel):
    csrf_token: str


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody
