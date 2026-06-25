"""研究任务接口 — 创建 / 列表 / 详情 / 删除 / SSE 事件流

对齐 API.md §3：
- POST /api/research — 创建研究任务 + Celery 分发
- GET /api/research — 任务历史列表（分页 + 状态筛选）
- GET /api/research/{task_id} — 任务状态与进度快照
- DELETE /api/research/{task_id} — FK CASCADE 级联删除
- GET /api/research/{task_id}/stream — SSE 事件流（实时进度推送）
- GET /api/research/{task_id}/state — REST 状态快照（轮询降级）
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_task_accessible
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.pipeline.sse_bridge import sse_event_stream
from app.schemas.research import ResearchCreateRequest
from app.services.research_service import (
    create_task,
    delete_task,
    get_report,
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
    2. 显式 commit —— CLAUDE.md 强制规则：delay() 前必须 commit
    3. Celery 分发 execute_research_task
    """
    result = await create_task(db, current_user["user_id"], req)
    await db.commit()
    _execute_research_task.delay(str(result.task_id))
    return {"code": "0", "message": "研究任务已创建", "data": result.model_dump()}


@router.get("")
async def list_research_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: str | None = Query(None, description="按状态筛选"),
    keyword: str | None = Query(None, description="按主题关键字搜索"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户的研究任务历史列表（分页）。

    对齐 API.md §3.1 GET /api/research。
    按 created_at DESC 排序，支持 status 筛选与 topic 关键字模糊搜索。
    """
    result = await get_task_list(
        db,
        user_id=current_user["user_id"],
        page=page,
        page_size=page_size,
        status=status,
        keyword=keyword,
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


@router.get("/{task_id}/stream")
async def stream_research_task_events(
    task: ResearchTask = Depends(require_task_accessible),
    db: AsyncSession = Depends(get_db),
):
    """SSE 事件流 —— 实时推送 Pipeline 进度。

    对齐 API.md §4 GET /api/research/{task_id}/stream。
    Content-Type: text/event-stream，15s 心跳。

    连接时立即推送 task.status.snapshot（当前完整状态），
    后续增量推送 phase.* / step.* / task.* 事件。
    """
    # 构建初始快照
    snapshot = await _build_snapshot(task, db)

    # 流式生成器
    async def event_stream():
        async for sse_text in sse_event_stream(str(task.id), snapshot):
            yield sse_text

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.get("/{task_id}/state")
async def get_research_task_state(
    task: ResearchTask = Depends(require_task_accessible),
    db: AsyncSession = Depends(get_db),
):
    """REST 状态快照 —— SSE 的等价物，供客户端轮询降级。

    对齐 API.md §3.6 GET /api/research/{task_id}/state。
    返回与 SSE task.status.snapshot 相同的数据结构。
    """
    snapshot = await _build_snapshot(task, db)
    return {"code": "0", "message": "ok", "data": snapshot}


@router.get("/{task_id}/report")
async def get_research_task_report(
    task: ResearchTask = Depends(require_task_accessible),
    db: AsyncSession = Depends(get_db),
):
    """获取完整研究报告（含 Evidence Graph 与 Trace）。

    对齐 API.md §3.3 GET /api/research/{task_id}/report。
    仅 completed / partially_completed 任务可获取。
    """
    result = await get_report(db, task)
    return {"code": "0", "message": "ok", "data": result.model_dump()}


# ── 辅助函数 ──────────────────────────────────────────────


async def _build_snapshot(
    task: ResearchTask,
    db: AsyncSession,
) -> dict:
    """构建任务状态快照（SSE 和 REST 共用）。

    快照结构：
    - task_id, status, current_phase
    - progress（completed_steps / total_steps / progress）
    - steps：已完成 Step 摘要列表
    - error：错误信息（如果失败）
    - 时间戳
    """
    # 刷新 task 以获取最新 steps（依赖 selectin 预加载）
    steps: list[ResearchStep] = task.steps if hasattr(task, "steps") else []

    # 步骤摘要
    steps_summary = []
    for s in steps:
        summary = {
            "step_id": str(s.id),
            "step_type": s.step_type,
            "status": s.status,
            "label": s.label,
        }
        if s.status == "completed" and s.output:
            # 根据 step_type 提取关键摘要字段
            if s.step_type == "planning":
                summary["sub_questions_count"] = len(
                    s.output.get("sub_questions", [])
                )
            elif s.step_type == "search":
                summary["after_dedup"] = s.output.get("after_dedup")
                summary["sources_created"] = s.output.get("sources_created")
            elif s.step_type == "fetch":
                summary["successful"] = s.output.get("successful")
                summary["failed"] = s.output.get("failed")
        if s.status == "failed":
            summary["error_code"] = s.error_code
            summary["error_message"] = s.error_message
        if s.duration_ms is not None:
            summary["duration_ms"] = s.duration_ms
        steps_summary.append(summary)

    # 进度
    total = task.total_steps or 0
    completed = task.completed_steps or 0
    progress = round(completed / total, 2) if total > 0 else 0.0

    snapshot: dict = {
        "task_id": str(task.id),
        "status": task.status,
        "current_phase": task.current_phase,
        "progress": {
            "completed_steps": completed,
            "total_steps": total,
            "progress": progress,
        },
        "steps": steps_summary,
        "topics": task.topic,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }

    # 错误信息（如果存在）
    if task.error_code:
        snapshot["error"] = {
            "error_code": task.error_code,
            "error_message": task.error_message,
            "recoverable": task.recoverable,
        }

    # 统计
    snapshot["stats"] = {
        "total_sources": task.total_sources or 0,
        "total_evidence": task.total_evidence or 0,
    }

    return snapshot
