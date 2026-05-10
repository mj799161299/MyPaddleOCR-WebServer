from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    invitation_code: str = Field(..., min_length=1, description="邀请码")


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdateRole(BaseModel):
    role: str = Field(..., pattern="^(admin|user)$")


class UserUpdateStatus(BaseModel):
    is_active: bool


class UserListResponse(BaseModel):
    users: List[UserResponse]
    total: int


class UserChangePassword(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=100)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int | None = None
