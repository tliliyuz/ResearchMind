"""研究任务业务逻辑 — 创建 / 列表 / 详情 / 删除

对齐 API.md §3.1：
- create_task()：校验 → 写入 research_tasks + 首个 research_step → commit → Celery 分发
- get_task_list()：当前用户任务分页列表，按 created_at DESC
- get_task_detail()：单任务状态 + progress 快照
- delete_task()：FK CASCADE 级联清理全部派生数据
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import (
    TaskNotFoundException,
    TaskAccessDeniedException,
    TaskStatusConflictException,
    TopicTooLongException,
    InvalidTaskTypeException,
    InvalidDepthException,
    InvalidRequirementsException,
)
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.schemas.research import (
    ResearchCreateRequest,
    ResearchCreateResponse,
    ResearchTaskResponse,
    ResearchTaskListItem,
    ResearchTaskListResponse,
    ProgressSchema,
    VALID_TASK_TYPES,
    VALID_DEPTHS,
)

logger = logging.getLogger(__name__)


# ── 创建任务 ────────────────────────────────────────────────────


async def create_task(
    db: AsyncSession,
    user_id: int,
    request: ResearchCreateRequest,
) -> ResearchCreateResponse:
    """创建研究任务 + 首个 Planning Step。

    1. 校验 topic 长度与 requirements 合法性
    2. 写入 research_tasks (status=pending)
    3. 写入首个 research_step (planning, pending)
    4. 返回 task_id + status + created_at

    注意：Celery 分发（commit + delay）由 API 层在返回前执行，
    避免在 Service 层 commit 破坏测试事务隔离。
    """
    _validate_create_request(request)

    now = datetime.now(timezone.utc)

    # 1. 创建研究任务
    task = ResearchTask(
        user_id=user_id,
        topic=request.topic.strip(),
        requirements=request.requirements.model_dump(),
        status="pending",
        current_phase=None,
        created_at=now,
    )
    db.add(task)
    await db.flush()  # 获取 task.id

    # 2. 创建首个 Planning Step（pending 状态，等待 Celery Worker 拾取）
    planning_step = ResearchStep(
        task_id=task.id,
        step_type="planning",
        status="pending",
        label="Planning：拆解研究主题",
    )
    db.add(planning_step)

    # 3. 更新 task 的步骤计数
    task.total_steps = 1

    # 4. flush 获取 ID（Celery 分发由 API 层在 commit 后执行，
    #    以避免 Service 层 commit 破坏测试事务隔离）
    await db.flush()

    logger.info(
        "研究任务已创建: task_id=%s, user_id=%d, topic=%s, task_type=%s",
        task.id, user_id, request.topic[:50], request.requirements.task_type,
    )

    return ResearchCreateResponse(
        task_id=task.id,
        status="pending",
        created_at=task.created_at,
    )


def _validate_create_request(request: ResearchCreateRequest) -> None:
    """校验创建请求的合法性。

    Pydantic 已做基础校验（topic ≤ 500 字符、task_type 枚举约束、
    max_sources 范围等），此处做补充业务校验。
    """
    if len(request.topic.strip()) == 0:
        raise TopicTooLongException()

    req = request.requirements
    if req.task_type not in VALID_TASK_TYPES:
        raise InvalidTaskTypeException()
    if req.depth not in VALID_DEPTHS:
        raise InvalidDepthException()
    if req.max_sources < 1 or req.max_sources > 50:
        raise InvalidRequirementsException("max_sources 必须在 1-50 之间")


# ── 任务列表 ────────────────────────────────────────────────────


async def get_task_list(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    keyword: str | None = None,
) -> ResearchTaskListResponse:
    """获取当前用户的研究任务历史列表。

    按 created_at DESC 排序，支持 status 筛选、topic 关键字模糊搜索与分页。
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100

    # 构建基础查询
    conditions = [ResearchTask.user_id == user_id]
    if status:
        conditions.append(ResearchTask.status == status)
    if keyword and keyword.strip():
        conditions.append(ResearchTask.topic.ilike(f"%{keyword.strip()}%"))

    # 总数查询
    count_q = select(func.count()).select_from(ResearchTask).where(*conditions)
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # 分页查询
    offset = (page - 1) * page_size
    q = (
        select(ResearchTask)
        .where(*conditions)
        .order_by(ResearchTask.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(q)
    tasks = result.scalars().all()

    # 构建列表项
    items = [_build_list_item(t) for t in tasks]

    return ResearchTaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


def _build_list_item(task: ResearchTask) -> ResearchTaskListItem:
    """从 ORM 对象构建列表项响应。

    从 requirements JSON 中提取 task_type 字段。
    """
    requirements = task.requirements or {}
    task_type = requirements.get("task_type", "unknown")

    return ResearchTaskListItem(
        task_id=task.id,
        topic=task.topic,
        status=task.status,
        task_type=task_type,
        total_sources=task.total_sources or 0,
        total_evidence=task.total_evidence or 0,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


# ── 任务详情 ────────────────────────────────────────────────────


async def get_task_detail(
    db: AsyncSession,
    task: ResearchTask,
) -> ResearchTaskResponse:
    """获取研究任务详情（含进度快照）。

    调用方需先通过 require_task_accessible 校验权限并获取 task 对象。
    """
    progress = _build_progress(task)
    return ResearchTaskResponse(
        task_id=task.id,
        topic=task.topic,
        status=task.status,
        current_phase=task.current_phase,
        requirements=task.requirements or {},
        progress=progress,
        total_sources=task.total_sources or 0,
        total_evidence=task.total_evidence or 0,
        error_code=task.error_code,
        error_message=task.error_message,
        recoverable=task.recoverable,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


def _build_progress(task: ResearchTask) -> ProgressSchema:
    """从 execution_context 或统计字段构建进度快照。

    API 响应中的 progress 是顶层便利字段，数据来源为
    execution_context.progress，fallback 到 total_steps / completed_steps。
    """
    ec = task.execution_context
    if ec and isinstance(ec, dict):
        pg = ec.get("progress")
        if pg and isinstance(pg, dict):
            return ProgressSchema(
                completed_steps=pg.get("completed_steps", task.completed_steps or 0),
                total_steps=pg.get("total_steps", task.total_steps or 0),
                progress=float(pg.get("progress", 0.0)),
            )

    # fallback：从统计列计算
    total = task.total_steps or 0
    completed = task.completed_steps or 0
    progress = (completed / total) if total > 0 else 0.0
    return ProgressSchema(
        completed_steps=completed,
        total_steps=total,
        progress=round(progress, 2),
    )


# ── 删除任务 ────────────────────────────────────────────────────


async def delete_task(
    db: AsyncSession,
    task: ResearchTask,
) -> None:
    """删除研究任务及其全部派生数据。

    FK ON DELETE CASCADE 自动清理：
    - research_steps (task_id CASCADE)
    - research_sources (task_id CASCADE)
    - evidence_items (task_id CASCADE)
    - report_sections (task_id CASCADE)
    - section_evidence (间接通过 section/evidence CASCADE)

    调用方需先通过 require_task_accessible 校验权限。
    """
    task_id = task.id
    # 使用 bulk DELETE 绕过 ORM 关系处理，避免 SQLite 驱动下
    # SQLAlchemy 在删除父表前尝试 SET NULL 子表 FK 的问题。
    await db.execute(sa_delete(ResearchTask).where(ResearchTask.id == task_id))
    await db.flush()

    logger.info("研究任务已删除: task_id=%s", task_id)
