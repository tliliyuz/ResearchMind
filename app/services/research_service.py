"""研究任务业务逻辑 — 创建 / 列表 / 详情 / 删除 / 报告获取

对齐 API.md §3.1 / §3.3：
- create_task()：校验 → 写入 research_tasks + 首个 research_step → commit → Celery 分发
- get_task_list()：当前用户任务分页列表，按 created_at DESC
- get_task_detail()：单任务状态 + progress 快照
- delete_task()：FK CASCADE 级联清理全部派生数据
- get_report()：获取完整研究报告（含 Evidence Graph 与 Trace）
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func, delete as sa_delete, update as sa_update
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
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.section_evidence import SectionEvidence
from app.schemas.research import (
    ProgressSchema,
    ReportSchema,
    ReportSectionSchema,
    ReportSectionSourceSchema,
    ReportSourceSchema,
    ResearchCancelResponse,
    ResearchCreateRequest,
    ResearchCreateResponse,
    ResearchReportResponse,
    ResearchTaskListItem,
    ResearchTaskListResponse,
    ResearchTaskResponse,
    VALID_DEPTHS,
    VALID_TASK_TYPES,
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


async def get_report(
    db: AsyncSession,
    task: ResearchTask,
) -> ResearchReportResponse:
    """获取完整研究报告（含 Evidence Graph 与 Trace）。

    调用方需先通过 require_task_accessible 校验权限并获取 task 对象。
    对齐 API.md §3.3 GET /api/research/{task_id}/report。
    """
    if task.status not in {"completed", "partially_completed"}:
        raise TaskStatusConflictException(detail="任务尚未完成，无法获取报告")

    # 读取最新完成的 Evidence Graph Step 的 output["graph"]
    stmt = (
        select(ResearchStep)
        .where(
            ResearchStep.task_id == task.id,
            ResearchStep.step_type == "evidence_graph",
            ResearchStep.status == "completed",
        )
        .order_by(ResearchStep.completed_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    eg_step: ResearchStep | None = result.scalar_one_or_none()

    if eg_step is None or not isinstance(eg_step.output, dict):
        raise TaskStatusConflictException(detail="报告尚未生成")

    evidence_graph = eg_step.output.get("graph") or {}

    # 构建 evidence_item.id -> evidence_index 映射
    items = evidence_graph.get("items") or []
    evidence_id_to_index: dict[int, int] = {}
    for item in items:
        if isinstance(item, dict) and "evidence_item_id" in item and "index" in item:
            evidence_id_to_index[item["evidence_item_id"]] = item["index"]

    # 组装章节（显式查询，避免 lazy load）
    stmt = (
        select(ReportSection)
        .where(ReportSection.task_id == task.id)
        .order_by(ReportSection.sort_order)
    )
    result = await db.execute(stmt)
    sorted_sections = list(result.scalars().all())

    section_ids = [s.id for s in sorted_sections]
    section_evidence_map: dict[int, list[int]] = {sid: [] for sid in section_ids}
    if section_ids:
        stmt = (
            select(SectionEvidence.section_id, SectionEvidence.evidence_id)
            .where(SectionEvidence.section_id.in_(section_ids))
        )
        result = await db.execute(stmt)
        for section_id, evidence_id in result.all():
            section_evidence_map.setdefault(section_id, []).append(evidence_id)

    # 预加载 evidence_items.source_id（用于生成 sources.id）
    evidence_ids = []
    for ids in section_evidence_map.values():
        evidence_ids.extend(ids)
    evidence_source_ids: dict[int, int] = {}
    if evidence_ids:
        stmt = select(EvidenceItem.id, EvidenceItem.source_id).where(EvidenceItem.id.in_(evidence_ids))
        result = await db.execute(stmt)
        for eid, source_id in result.all():
            evidence_source_ids[eid] = source_id

    report_sections: list[ReportSectionSchema] = []
    for section in sorted_sections:
        section_sources: list[ReportSectionSourceSchema] = []
        seen_indices: set[int] = set()
        for evidence_id in section_evidence_map.get(section.id, []):
            idx = evidence_id_to_index.get(evidence_id)
            if idx is None or idx in seen_indices:
                continue
            seen_indices.add(idx)
            section_sources.append(ReportSectionSourceSchema(
                id=evidence_source_ids.get(evidence_id, 0),
                evidence_index=idx,
            ))
        section_sources.sort(key=lambda x: x.evidence_index)
        report_sections.append(ReportSectionSchema(
            heading=section.heading,
            content=section.content,
            sources=section_sources,
        ))

    # 组装报告来源
    report_sources: list[ReportSourceSchema] = []
    for src in evidence_graph.get("sources") or []:
        if not isinstance(src, dict):
            continue
        report_sources.append(ReportSourceSchema(
            id=src.get("id") or 0,
            url=src.get("url") or "",
            title=src.get("title") or "",
            domain=src.get("domain") or "",
        ))

    # 报告生成时间
    generated_at = eg_step.completed_at
    graph_generated_at = evidence_graph.get("generated_at")
    if graph_generated_at:
        try:
            generated_at = datetime.fromisoformat(graph_generated_at)
        except (ValueError, TypeError):
            pass
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)

    report = ReportSchema(
        title=task.topic,
        generated_at=generated_at,
        sections=report_sections,
        sources=report_sources,
    )

    return ResearchReportResponse(
        task_id=task.id,
        status=task.status,
        report=report,
        evidence_graph=evidence_graph,
        trace=task.trace,
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


# ── 取消任务 ────────────────────────────────────────────────────


TERMINAL_STATUSES: frozenset[str] = frozenset({
    "completed", "failed", "partially_completed", "canceled"
})


async def cancel_task(
    db: AsyncSession,
    task: ResearchTask,
) -> ResearchCancelResponse:
    """取消研究任务。

    对齐 API.md §3.2 POST /api/research/{task_id}/cancel：
    - 终态校验：completed / failed / partially_completed / canceled 抛 E2003
    - CAS 更新：仅当 status 为 pending / running 时才可取消
    - CAS 失败意味着并发状态变更，同样抛 E2003

    注意：本函数不提交事务，由 API 层依赖注入的 get_db 统一提交。
    """
    if task.status in TERMINAL_STATUSES:
        raise TaskStatusConflictException(detail="任务已处于终态，无法取消")

    now = datetime.now(timezone.utc)
    result = await db.execute(
        sa_update(ResearchTask)
        .where(
            ResearchTask.id == task.id,
            ResearchTask.status.in_(["pending", "running"]),
        )
        .values(status="canceled", completed_at=now)
    )
    if result.rowcount == 0:
        raise TaskStatusConflictException(detail="任务状态已变更，无法取消")

    # 同步内存对象，避免后续读取到旧状态
    task.status = "canceled"
    task.completed_at = now

    logger.info("研究任务已取消: task_id=%s", task.id)
    return ResearchCancelResponse(task_id=task.id, status="canceled")


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
