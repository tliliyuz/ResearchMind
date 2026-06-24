"""研究任务接口 — 创建 / 列表 / 详情 / 删除

对齐 API.md §3.1：
- POST /api/research — 创建研究任务 + Celery 分发
- GET /api/research — 任务历史列表（分页 + 状态筛选）
- GET /api/research/{task_id} — 任务状态与进度快照
- DELETE /api/research/{task_id} — FK CASCADE 级联删除
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_task_accessible
from app.models.research_task import ResearchTask
from app.schemas.research import ResearchCreateRequest
from app.services.research_service import (
    create_task,
    delete_task,
    get_task_detail,
    get_task_list,
)
from app.tasks.research_task import execute_research_task as _execute_research_task

router = APIRouter(tags=["研究任务"])


@router.post("", status_code=201)
async def create_research_task(
    req: ResearchCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建研究任务（需登录）。

    对齐 API.md §3.1 POST /api/research。
    1. Service 层写入 task + 首个 planning step（flush）
    2. Celery 分发 execute_research_task
    3. get_db 依赖在响应返回后自动 commit

    注：delay() 在 get_db commit 之前调用存在微小的竞态窗口，
    但 Celery Worker 内置了幂等检查（task 不存在时优雅跳过），
    v1.0 可接受此设计。
    """
    result = await create_task(db, current_user["user_id"], req)
    _execute_research_task.delay(str(result.task_id))
    return {"code": "0", "message": "研究任务已创建", "data": result.model_dump()}


@router.get("")
async def list_research_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: str | None = Query(None, description="按状态筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户的研究任务历史列表（分页）。

    对齐 API.md §3.1 GET /api/research。
    按 created_at DESC 排序，支持 status 筛选。
    """
    result = await get_task_list(
        db,
        user_id=current_user["user_id"],
        page=page,
        page_size=page_size,
        status=status,
    )
    return {"code": "0", "message": "ok", "data": result.model_dump()}


@router.get("/{task_id}")
async def get_research_task_detail(
    task: ResearchTask = Depends(require_task_accessible),
    db: AsyncSession = Depends(get_db),
):
    """获取研究任务详情（需登录，仅 owner 或 admin）。

    对齐 API.md §3.1 GET /api/research/{task_id}。
    含 status / current_phase / progress 进度快照。

    注：FastAPI 依赖缓存机制确保 require_task_accessible 内部的 get_db
    与此处的 get_db 返回同一会话实例。
    """
    result = await get_task_detail(db, task)
    return {"code": "0", "message": "ok", "data": result.model_dump()}


@router.delete("/{task_id}")
async def delete_research_task(
    task: ResearchTask = Depends(require_task_accessible),
    db: AsyncSession = Depends(get_db),
):
    """删除研究任务（需登录，仅 owner 或 admin）。

    对齐 API.md §3.1 DELETE /api/research/{task_id}。
    FK ON DELETE CASCADE 自动清理全部派生数据（Steps / Sources / Evidence / Report Sections）。
    """
    await delete_task(db, task)
    return {"code": "0", "message": "研究任务已删除", "data": None}
