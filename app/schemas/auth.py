"""认证相关请求/响应模型 — 对齐 API.md §2

提供注册、登录、Token 刷新、退出、改密所需的 Pydantic Schema。
"""

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    """注册请求 — username 2-64 字符（不可纯数字），password 6-128 字符。"""

    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username_not_numeric(cls, v: str) -> str:
        """拒绝纯数字/纯空格用户名。"""
        stripped = v.strip()
        if not stripped:
            raise ValueError("用户名不能为空")
        if re.match(r"^\d+$", stripped):
            raise ValueError("用户名不能为纯数字，请包含文字或字母")
        return v


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    """Token 刷新请求。"""

    refresh_token: str


class LogoutRequest(BaseModel):
    """退出登录请求。"""

    refresh_token: str


class ChangePasswordRequest(BaseModel):
    """修改密码请求。"""

    old_password: str = Field(..., min_length=6, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    """Token 对响应。

    access_token：JWT 短有效期（15min）
    refresh_token：JWT 长有效期（7天），SHA-256 哈希存 MySQL
    expires_in：access_token 有效期（秒）
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """用户信息响应。"""

    id: int
    username: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}
