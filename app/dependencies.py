"""依赖注入模块 — DB 会话、当前用户、Task 访问权限。

提供 FastAPI 路由所需的通用依赖：
  - get_db: 异步数据库会话（yield session + 自动 commit/rollback）
  - get_current_user: 从 request.state 读取已认证用户 + DB 状态校验
  - require_task_accessible: 校验当前用户有权访问指定研究任务

对齐 ARCHITECTURE.md §4 权限模型：
  - AuthMiddleware（ASGI）先验证 JWT 并将 user_id/username/role 写入 request.state
  - get_current_user 从 request.state 读取 + 查 DB 校验 status=active
  - require_task_accessible：owner→允许 / 其他→E2002
"""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.core.exceptions import (
    InvalidTokenException,
    TaskAccessDeniedException,
    TaskNotFoundException,
    UserDisabledException,
)
from app.models.user import User
from app.models.research_task import ResearchTask


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
        InvalidTokenException (E1004): 请求中缺少认证信息
        UserDisabledException (E1010): 用户已被禁用
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise InvalidTokenException("请求中缺少用户认证信息")

    # 校验用户是否被禁用（主键查询，毫秒级）
    user = await db.get(User, user_id)
    if user is None or user.status == "disabled":
        raise UserDisabledException()

    username = getattr(request.state, "username", None)
    role = getattr(request.state, "role", None)

    return {
        "user_id": user_id,
        "username": username,
        "role": role,
    }


# ── Task 访问权限依赖注入 ─────────────────────────────────────


async def require_task_accessible(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ResearchTask:
    """依赖注入：校验当前用户有权访问指定研究任务。

    Task 级权限：
    - owner → 允许
    - 其他 → E2002 (TaskAccessDenied)

    通过 FastAPI 路径参数 {task_id} 自动注入。

    用法：
        @router.get("/api/research/{task_id}")
        async def detail(task: ResearchTask = Depends(require_task_accessible)):
            ...

    对齐 ARCHITECTURE.md §4 与 API.md §7 权限矩阵。
    """
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(ResearchTask)
        .options(selectinload(ResearchTask.steps))
        .where(ResearchTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundException(task_id)

    if task.user_id != current_user["user_id"]:
        raise TaskAccessDeniedException()

    # [Planned: v1.5] 审计日志 hook
    # await audit_log("task_access", user_id=current_user["user_id"], task_id=task_id)

    return task
