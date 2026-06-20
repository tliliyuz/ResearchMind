"""认证接口 — 注册 / 登录 / Token 刷新 / 退出 / 改密

对齐 API.md §2：
- POST /api/auth/register — 注册
- POST /api/auth/login — 登录（返回 access_token + refresh_token）
- POST /api/auth/refresh — Token 刷新（Rotation）
- POST /api/auth/logout — 吊销 refresh_token
- PUT /api/auth/password — 改密 + 吊销全部 refresh_token
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.services.auth_service import (
    change_password,
    login,
    logout,
    refresh,
    register,
)

router = APIRouter(tags=["认证"])


@router.post("/register", status_code=201)
async def register_user(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册新用户（公开接口）。

    对齐 API.md §2 POST /api/auth/register。
    """
    user = await register(db, req.username, req.password)
    return {"code": "0", "message": "注册成功", "data": user.model_dump()}


@router.post("/login")
async def login_user(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录（公开接口）。

    对齐 API.md §2 POST /api/auth/login。
    返回 access_token（15min）+ refresh_token（7天）+ expires_in（秒）。
    """
    token = await login(db, req.username, req.password)
    return {"code": "0", "message": "登录成功", "data": token.model_dump()}


@router.post("/refresh")
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """刷新 Token（公开接口，Rotation 机制）。

    对齐 API.md §2 POST /api/auth/refresh。
    旧 refresh_token 立即吊销，签发新 token 对。
    泄露检测：已吊销 token 被重用 → E1009，全量吊销该用户全部 session。
    """
    token = await refresh(db, req.refresh_token)
    return {"code": "0", "message": "Token 刷新成功", "data": token.model_dump()}


@router.post("/logout")
async def logout_user(
    req: LogoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """退出登录（需认证 — AuthMiddleware 验证 Bearer Token）。

    对齐 API.md §2 POST /api/auth/logout。
    吊销当前 refresh_token，同时校验 access_token 的 user_id 与 refresh_token 一致。
    """
    await logout(db, req.refresh_token, current_user["user_id"])
    return {"code": "0", "message": "已退出登录", "data": None}


@router.put("/password")
async def change_user_password(
    req: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """修改密码（需认证）。

    对齐 API.md §2 PUT /api/auth/password。
    验证旧密码 → 更新密码哈希 → 吊销该用户全部 refresh_token（强制下线）。
    """
    await change_password(db, current_user["user_id"], req.old_password, req.new_password)
    return {"code": "0", "message": "密码修改成功，所有设备已下线", "data": None}
