"""依赖注入模块 — DB 会话、当前用户、管理员权限。

提供 FastAPI 路由所需的通用依赖：
  - get_db: 异步数据库会话（yield session + 自动 commit/rollback）
  - get_current_user: 从 request.state 读取已认证用户 + DB 状态校验
  - require_admin: 要求当前用户为 admin 角色

对齐 ARCHITECTURE.md §4 权限模型：
  - AuthMiddleware（ASGI）先验证 JWT 并将 user_id/username/role 写入 request.state
  - get_current_user 从 request.state 读取 + 查 DB 校验 status=active
  - require_admin 在 get_current_user 基础上校验 role=admin
"""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.exceptions import PermissionDeniedException, UserDisabledException
from app.models.user import User


# ── DB 会话依赖注入 ──────────────────────────────────────────


async def get_db():
    """FastAPI 依赖注入：提供异步数据库会话。

    每次请求获取一个异步 DB session，结束时自动 commit（成功）或 rollback（异常）。

    用法：
        @router.get("/something")
        async def handler(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── 当前用户依赖注入 ──────────────────────────────────────────


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """从 request.state 获取已认证用户信息（由 AuthMiddleware 注入），
    并校验用户 status 是否被禁用。

    复用路由处理器的 get_db() session，避免每次请求开启额外数据库连接。

    路由中通过 Depends(get_current_user) 使用。

    Returns:
        dict: {"user_id": int, "username": str, "role": str}

    Raises:
        UserDisabledException (E1010): 用户已被禁用
    """
    user_id = request.state.user_id

    # 校验用户是否被禁用（主键查询，毫秒级）
    user = await db.get(User, user_id)
    if user is None or user.status == "disabled":
        raise UserDisabledException()

    return {
        "user_id": user_id,
        "username": request.state.username,
        "role": request.state.role,
    }


# ── 管理员权限依赖注入 ───────────────────────────────────────


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """依赖注入：要求当前用户为 admin 角色。

    对齐 API.md §5.1：所有 /api/admin/* 端点要求 role=admin，
    非 admin 返回 403 E1005。

    用法：
        @router.get("/api/admin/stats")
        async def stats(current_user: dict = Depends(require_admin)):
            ...
    """
    if current_user.get("role") != "admin":
        raise PermissionDeniedException()
    return current_user
