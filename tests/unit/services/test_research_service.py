"""研究任务 Service 单元测试 — 覆盖 create_task / get_task_list / get_task_detail / delete_task

对齐 TESTING_STRATEGY.md：
- 每个操作成功+失败+所有错误分支独立用例
- 强断言：验证具体值/顺序/错误码
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    TopicTooLongException,
    InvalidTaskTypeException,
    InvalidDepthException,
    InvalidRequirementsException,
    TaskNotFoundException,
    TaskAccessDeniedException,
    TaskStatusConflictException,
)
from app.core.security import hash_password
from app.models.user import User
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.research_source import ResearchSource
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.section_evidence import SectionEvidence
from app.schemas.research import ResearchCreateRequest
from app.services.research_service import (
    _build_progress,
    cancel_task,
    create_task,
    get_report,
    get_task_list,
    get_task_detail,
    delete_task,
    retry_task,
    RETRY_ALLOWED_STATUSES,
)


# ═══════════════════════════════════════════════════════════════
# Autouse fixture — 确保 FK 引用的用户存在
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
async def seed_test_users(db_session: AsyncSession):
    """预置测试用户：user_id=1, user_id=2。

    所有 Service 测试都需要用户存在（research_tasks 的 FK 约束）。
    """
    users = [
        User(id=1, username="testuser", password_hash=hash_password("pass"), role="user", status="active"),
        User(id=2, username="other", password_hash=hash_password("pass"), role="user", status="active"),
    ]
    for u in users:
        existing = await db_session.get(User, u.id)
        if existing is None:
            db_session.add(u)
    await db_session.flush()


# ═══════════════════════════════════════════════════════════════
# _build_progress
# ═══════════════════════════════════════════════════════════════


class TestBuildProgress:
    """进度快照构建：确保进度比例始终落在 [0, 1] 区间。"""

    def test_execution_context中progress大于1时锁定为1(self):
        task = ResearchTask(
            id="task-001",
            user_id=1,
            topic="test",
            requirements={},
            total_steps=7,
            completed_steps=11,
            execution_context={
                "progress": {
                    "completed_steps": 11,
                    "total_steps": 7,
                    "progress": 1.57,
                }
            },
        )
        progress = _build_progress(task)
        assert progress.progress == 1.0
        assert progress.completed_steps == 11
        assert progress.total_steps == 7

    def test_fallback统计列progress大于1时锁定为1(self):
        task = ResearchTask(
            id="task-002",
            user_id=1,
            topic="test",
            requirements={},
            total_steps=7,
            completed_steps=11,
            execution_context=None,
        )
        progress = _build_progress(task)
        assert progress.progress == 1.0
        assert progress.completed_steps == 11
        assert progress.total_steps == 7

    def test_execution_context中progress小于0时锁定为0(self):
        task = ResearchTask(
            id="task-003",
            user_id=1,
            topic="test",
            requirements={},
            total_steps=7,
            completed_steps=0,
            execution_context={
                "progress": {
                    "completed_steps": 0,
                    "total_steps": 7,
                    "progress": -0.5,
                }
            },
        )
        progress = _build_progress(task)
        assert progress.progress == 0.0


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


def _make_request(
    topic="量子计算对密码学的影响",
    task_type="analysis",
    depth="quick",
    max_sources=10,
    language="zh",
) -> ResearchCreateRequest:
    """工厂函数：创建合法的 ResearchCreateRequest。"""
    return ResearchCreateRequest(
        topic=topic,
        requirements={
            "task_type": task_type,
            "depth": depth,
            "max_sources": max_sources,
            "language": language,
        },
    )


async def _seed_user(db: AsyncSession, user_id: int = 1, username: str = "testuser") -> None:
    """工厂函数：确保 users 表中存在指定 user_id。"""
    existing = await db.get(User, user_id)
    if existing is None:
        user = User(
            id=user_id,
            username=username,
            password_hash=hash_password("testpass123"),
            role="user",
            status="active",
        )
        db.add(user)
        await db.flush()


async def _seed_task(db: AsyncSession, user_id: int = 1, **overrides) -> ResearchTask:
    """工厂函数：在 DB 中创建一条 ResearchTask（含关联 user）。"""
    await _seed_user(db, user_id)
    """工厂函数：在 DB 中创建一条 ResearchTask。"""
    task = ResearchTask(
        user_id=user_id,
        topic=overrides.get("topic", "测试研究主题"),
        requirements=overrides.get("requirements", {"task_type": "analysis", "depth": "quick"}),
        status=overrides.get("status", "pending"),
        current_phase=overrides.get("current_phase"),
    )
    db.add(task)
    await db.flush()

    step = ResearchStep(
        task_id=task.id,
        step_type="planning",
        status="completed" if task.status == "completed" else "pending",
    )
    db.add(step)
    await db.flush()
    return task


# ═══════════════════════════════════════════════════════════════
# create_task()
# ═══════════════════════════════════════════════════════════════


class TestCreateTask:
    """创建研究任务"""

    async def test_正常创建_返回task_id和pending状态(self, db_session: AsyncSession):
        req = _make_request()
        result = await create_task(db_session, user_id=1, request=req)

        assert result.task_id != ""
        assert len(result.task_id) == 36  # UUID 格式
        assert result.status == "pending"
        assert result.created_at is not None

    async def test_创建后task写入数据库(self, db_session: AsyncSession):
        req = _make_request()
        result = await create_task(db_session, user_id=1, request=req)

        # 验证 task 行存在
        task = await db_session.get(ResearchTask, result.task_id)
        assert task is not None
        assert task.topic == "量子计算对密码学的影响"
        assert task.user_id == 1
        assert task.status == "pending"
        # 创建时初始化为七阶段总数（与 PHASE_ORDER 一致），分母固定不再动态扩展
        assert task.total_steps == 7

    async def test_创建后附首个planning_step(self, db_session: AsyncSession):
        req = _make_request()
        result = await create_task(db_session, user_id=1, request=req)

        # 验证 research_step 行存在
        q = select(ResearchStep).where(ResearchStep.task_id == result.task_id)
        step_result = await db_session.execute(q)
        steps = step_result.scalars().all()
        assert len(steps) == 1
        assert steps[0].step_type == "planning"
        assert steps[0].status == "pending"
        assert steps[0].label == "Planning：拆解研究主题"

    async def test_requirements正确存储(self, db_session: AsyncSession):
        req = _make_request(task_type="comparison", max_sources=25, language="en")
        result = await create_task(db_session, user_id=1, request=req)

        task = await db_session.get(ResearchTask, result.task_id)
        assert task.requirements["task_type"] == "comparison"
        assert task.requirements["max_sources"] == 25
        assert task.requirements["language"] == "en"

    async def test_三种task_type全部可创建(self, db_session: AsyncSession):
        for tt in ("comparison", "explainer", "analysis"):
            req = _make_request(task_type=tt)
            result = await create_task(db_session, user_id=1, request=req)
            task = await db_session.get(ResearchTask, result.task_id)
            assert task.requirements["task_type"] == tt

    async def test_不同用户创建任务隔离(self, db_session: AsyncSession):
        req1 = _make_request(topic="用户1的研究")
        r1 = await create_task(db_session, user_id=1, request=req1)

        req2 = _make_request(topic="用户2的研究")
        r2 = await create_task(db_session, user_id=2, request=req2)

        t1 = await db_session.get(ResearchTask, r1.task_id)
        t2 = await db_session.get(ResearchTask, r2.task_id)
        assert t1.user_id == 1
        assert t2.user_id == 2
        assert t1.id != t2.id

    # ── 错误分支 ──────────────────────────────────────────────

    async def test_topic超500字符_抛出ValidationError(self, db_session: AsyncSession):
        """Pydantic 已拦截 >500，此处验证 Pydantic 的拦截。"""
        with pytest.raises(ValidationError):
            _make_request(topic="研" * 501)

    async def test_topic纯空格_抛出ValidationError(self, db_session: AsyncSession):
        with pytest.raises(ValidationError):
            _make_request(topic="   ")


# ═══════════════════════════════════════════════════════════════
# get_task_list()
# ═══════════════════════════════════════════════════════════════


class TestGetTaskList:
    """研究任务列表"""

    async def test_空列表_返回total为0(self, db_session: AsyncSession):
        result = await get_task_list(db_session, user_id=1)
        assert result.total == 0
        assert result.page == 1
        assert len(result.items) == 0

    async def test_单条记录_返回正确列表项(self, db_session: AsyncSession):
        await _seed_task(db_session, user_id=1, topic="测试主题")

        result = await get_task_list(db_session, user_id=1)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].topic == "测试主题"
        assert result.items[0].status == "pending"
        assert result.items[0].task_type == "analysis"

    async def test_多条记录_按created_at降序排列(self, db_session: AsyncSession):
        """验证最新创建的任务排在前面。使用显式时间戳保证确定性。"""
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        t1 = await _seed_task(db_session, user_id=1, topic="旧任务")
        t1.created_at = now - timedelta(hours=1)
        t2 = await _seed_task(db_session, user_id=1, topic="新任务")
        t2.created_at = now
        await db_session.flush()

        result = await get_task_list(db_session, user_id=1)
        assert result.total == 2
        # 最新创建的排前面
        assert result.items[0].topic == "新任务"
        assert result.items[1].topic == "旧任务"

    async def test_分页_第一页(self, db_session: AsyncSession):
        for i in range(5):
            await _seed_task(db_session, user_id=1, topic=f"任务{i}")

        result = await get_task_list(db_session, user_id=1, page=1, page_size=2)
        assert result.total == 5
        assert result.page == 1
        assert result.page_size == 2
        assert len(result.items) == 2

    async def test_分页_第二页(self, db_session: AsyncSession):
        for i in range(5):
            await _seed_task(db_session, user_id=1, topic=f"任务{i}")

        result = await get_task_list(db_session, user_id=1, page=2, page_size=2)
        assert result.total == 5
        assert result.page == 2
        assert len(result.items) == 2

    async def test_分页_超出范围返回空(self, db_session: AsyncSession):
        for i in range(3):
            await _seed_task(db_session, user_id=1, topic=f"任务{i}")

        result = await get_task_list(db_session, user_id=1, page=10, page_size=20)
        assert result.total == 3
        assert len(result.items) == 0

    async def test_按status筛选(self, db_session: AsyncSession):
        await _seed_task(db_session, user_id=1, topic="pending任务", status="pending")
        await _seed_task(db_session, user_id=1, topic="completed任务", status="completed")
        await _seed_task(db_session, user_id=1, topic="failed任务", status="failed")

        result = await get_task_list(db_session, user_id=1, status="completed")
        assert result.total == 1
        assert result.items[0].status == "completed"
        assert result.items[0].topic == "completed任务"

    async def test_仅返回当前用户任务(self, db_session: AsyncSession):
        await _seed_task(db_session, user_id=1, topic="用户1的任务")
        await _seed_task(db_session, user_id=2, topic="用户2的任务")

        result = await get_task_list(db_session, user_id=1)
        assert result.total == 1
        assert result.items[0].topic == "用户1的任务"

    async def test_page_size上限100(self, db_session: AsyncSession):
        """page_size > 100 时被限制为 100。"""
        result = await get_task_list(db_session, user_id=1, page_size=200)
        assert result.page_size == 100

    async def test_page为0自动修正为1(self, db_session: AsyncSession):
        result = await get_task_list(db_session, user_id=1, page=0)
        assert result.page == 1


# ═══════════════════════════════════════════════════════════════
# get_task_detail()
# ═══════════════════════════════════════════════════════════════


class TestGetTaskDetail:
    """研究任务详情"""

    async def test_正常获取详情_含完整字段(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1, topic="详情测试")

        result = await get_task_detail(db_session, task)
        assert result.task_id == task.id
        assert result.topic == "详情测试"
        assert result.status == "pending"
        assert result.requirements["task_type"] == "analysis"
        assert result.total_sources == 0
        assert result.total_evidence == 0

    async def test_running状态_含current_phase(self, db_session: AsyncSession):
        task = await _seed_task(
            db_session, user_id=1, status="running", current_phase="searching"
        )
        result = await get_task_detail(db_session, task)
        assert result.status == "running"
        assert result.current_phase == "searching"

    async def test_failed状态_含错误信息(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1, status="failed")
        task.error_code = "E3101"
        task.error_message = "LLM 无法拆解研究主题"
        task.recoverable = False
        await db_session.flush()

        result = await get_task_detail(db_session, task)
        assert result.error_code == "E3101"
        assert result.error_message == "LLM 无法拆解研究主题"
        assert result.recoverable is False

    async def test_有execution_context时_优先从中提取progress(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1)
        task.execution_context = {
            "current_phase": "searching",
            "progress": {
                "completed_steps": 5,
                "total_steps": 10,
                "progress": 0.5,
            },
        }
        task.completed_steps = 1  # 统计列落后于 execution_context
        task.total_steps = 1
        await db_session.flush()

        result = await get_task_detail(db_session, task)
        assert result.progress.completed_steps == 5
        assert result.progress.total_steps == 10
        assert result.progress.progress == 0.5

    async def test_无execution_context时_fallback到统计列(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1)
        task.total_steps = 10
        task.completed_steps = 3
        task.execution_context = None
        await db_session.flush()

        result = await get_task_detail(db_session, task)
        assert result.progress.completed_steps == 3
        assert result.progress.total_steps == 10
        assert result.progress.progress == 0.3

    async def test_total_steps为0时_progress为0(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1)
        task.total_steps = 0
        task.completed_steps = 0
        task.execution_context = None
        await db_session.flush()

        result = await get_task_detail(db_session, task)
        assert result.progress.progress == 0.0


# ═══════════════════════════════════════════════════════════════
# delete_task()
# ═══════════════════════════════════════════════════════════════


class TestDeleteTask:
    """删除研究任务"""

    async def test_删除后任务不存在(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1)
        task_id = task.id

        await delete_task(db_session, task)

        deleted = await db_session.get(ResearchTask, task_id)
        assert deleted is None

    async def test_级联删除关联步骤(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1)
        task_id = task.id

        # 验证 step 存在
        q = select(func.count()).select_from(ResearchStep).where(ResearchStep.task_id == task_id)
        count_result = await db_session.execute(q)
        assert count_result.scalar() == 1

        await delete_task(db_session, task)

        # 验证 step 也被删除
        count_result = await db_session.execute(q)
        assert count_result.scalar() == 0

    async def test_仅删除指定任务_不影响其他任务(self, db_session: AsyncSession):
        t1 = await _seed_task(db_session, user_id=1, topic="任务1")
        t2 = await _seed_task(db_session, user_id=1, topic="任务2")

        await delete_task(db_session, t1)

        # t1 已删除
        assert await db_session.get(ResearchTask, t1.id) is None
        # t2 仍在
        assert await db_session.get(ResearchTask, t2.id) is not None


# ═══════════════════════════════════════════════════════════════
# cancel_task()
# ═══════════════════════════════════════════════════════════════


class TestCancelTask:
    """取消研究任务"""

    async def test_pending任务_取消成功(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1, status="pending")

        result = await cancel_task(db_session, task)

        assert result.task_id == task.id
        assert result.status == "canceled"
        assert task.status == "canceled"
        assert task.completed_at is not None

    async def test_running任务_取消成功(self, db_session: AsyncSession):
        task = await _seed_task(db_session, user_id=1, status="running")

        result = await cancel_task(db_session, task)

        assert result.status == "canceled"
        assert task.status == "canceled"

    async def test_已终态抛出E2003(self, db_session: AsyncSession):
        for status in ["completed", "failed", "partially_completed", "canceled"]:
            task = await _seed_task(db_session, user_id=1, status=status)
            with pytest.raises(TaskStatusConflictException) as exc_info:
                await cancel_task(db_session, task)
            assert exc_info.value.error_code == "E2003"

    async def test_CAS失败抛出E2003(self, db_session: AsyncSession):
        """内存状态为 running，但 DB 已被改为 completed，CAS 失败。"""
        task = await _seed_task(db_session, user_id=1, status="running")
        from sqlalchemy import update as sa_update
        await db_session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task.id)
            .values(status="completed")
        )
        await db_session.flush()

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await cancel_task(db_session, task)

        assert exc_info.value.error_code == "E2003"


# ═══════════════════════════════════════════════════════════════
# get_report()
# ═══════════════════════════════════════════════════════════════


async def _seed_report_task(db: AsyncSession, status: str = "completed") -> ResearchTask:
    """工厂函数：预置一个含 Evidence Graph 与 ReportSection 的任务。"""
    task = ResearchTask(
        id="task-report-service-001",
        user_id=1,
        topic="量子计算对密码学的影响",
        requirements={"task_type": "analysis", "depth": "quick", "max_sources": 10, "language": "zh"},
        status=status,
        total_steps=7,
        completed_steps=7,
        completed_at=datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc),
    )
    db.add(task)
    await db.flush()

    source = ResearchSource(
        task_id=task.id,
        url="https://example.com/source-0",
        title="来源 0",
        domain="example.com",
        content="量子计算对 RSA 算法构成严重威胁。",
        fetch_status="success",
        fetched_at=datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
    )
    db.add(source)
    await db.flush()

    ev = EvidenceItem(
        task_id=task.id,
        source_id=source.id,
        content="量子计算对 RSA 算法构成严重威胁。",
        relevance_score=0.95,
    )
    db.add(ev)
    await db.flush()

    evidence_graph_step = ResearchStep(
        id="step-eg-report-service-001",
        task_id=task.id,
        step_type="evidence_graph",
        status="completed",
        output={
            "graph": {
                "task_id": task.id,
                "generated_at": datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc).isoformat(),
                "items": [
                    {
                        "index": 0,
                        "evidence_item_id": ev.id,
                        "source_id": source.id,
                        "source_url": source.url,
                        "source_title": source.title,
                        "domain": source.domain,
                        "content": ev.content,
                        "relevance_score": 0.95,
                        "used_in_sections": [],
                    }
                ],
                "clusters": [],
                "conflicts": [],
                "knowledge_gaps": [],
                "sources": [
                    {
                        "id": source.id,
                        "url": source.url,
                        "title": source.title,
                        "domain": source.domain,
                        "evidence_count": 1,
                    }
                ],
            }
        },
        started_at=datetime(2026, 1, 1, 0, 0, 6, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc),
        duration_ms=1000,
    )
    db.add(evidence_graph_step)

    section = ReportSection(
        task_id=task.id,
        heading="1. 概述",
        content="量子计算威胁[来源0]。",
        sort_order=0,
    )
    db.add(section)
    await db.flush()

    db.add(SectionEvidence(section_id=section.id, evidence_id=ev.id))
    await db.flush()

    return task


class TestGetReport:
    """获取研究报告"""

    async def test_已完成任务返回完整报告(self, db_session: AsyncSession):
        task = await _seed_report_task(db_session, status="completed")

        result = await get_report(db_session, task)

        assert result.task_id == task.id
        assert result.status == "completed"
        assert result.report.title == task.topic
        assert len(result.report.sections) == 1
        assert result.report.sections[0].heading == "1. 概述"
        assert len(result.report.sections[0].sources) == 1
        assert result.report.sections[0].sources[0].id == 1
        assert result.report.sections[0].sources[0].evidence_index == 0
        assert len(result.report.sources) == 1
        assert result.report.sources[0].domain == "example.com"
        assert result.evidence_graph["items"][0]["index"] == 0
        assert result.trace is None

    async def test_partially_completed任务可获取报告(self, db_session: AsyncSession):
        task = await _seed_report_task(db_session, status="partially_completed")

        result = await get_report(db_session, task)

        assert result.status == "partially_completed"
        assert len(result.report.sections) == 1

    async def test_运行中任务_抛出E2003(self, db_session: AsyncSession):
        task = await _seed_report_task(db_session, status="running")

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await get_report(db_session, task)

        assert exc_info.value.error_code == "E2003"

    async def test_无EvidenceGraphStep_抛出E2003(self, db_session: AsyncSession):
        task = ResearchTask(
            id="task-report-no-eg-001",
            user_id=1,
            topic="无证据图",
            requirements={"task_type": "analysis"},
            status="completed",
        )
        db_session.add(task)
        await db_session.flush()

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await get_report(db_session, task)

        assert exc_info.value.error_code == "E2003"


# ═══════════════════════════════════════════════════════════════
# retry_task()
# ═══════════════════════════════════════════════════════════════


async def _seed_retry_task(
    db: AsyncSession,
    *,
    status: str = "failed",
    recoverable: bool | None = True,
    execution_context: dict | None = None,
    with_failed_step: bool = False,
    with_completed_step: bool = False,
) -> ResearchTask:
    """工厂函数：预置一个可 retry 的任务（含基础 step）。

    - status: 任务状态（failed / partially_completed / canceled）
    - recoverable: 是否可恢复
    - execution_context: 断点续跑上下文（含 last_completed_step_id / execution_pointer）
    - with_failed_step: 是否附带一条 failed step（用于验证重置逻辑）
    - with_completed_step: 是否附带一条 completed step（用于验证复用不重置）
    """
    task = ResearchTask(
        user_id=1,
        topic="断点续跑测试主题",
        requirements={"task_type": "analysis", "depth": "quick", "max_sources": 10, "language": "zh"},
        status=status,
        recoverable=recoverable,
        execution_context=execution_context,
        total_steps=7,
        completed_steps=3 if status == "partially_completed" else 0,
        error_code="E3104" if status == "failed" else None,
        error_message="LLM 综合失败" if status == "failed" else None,
    )
    db.add(task)
    await db.flush()

    # 基础 planning step（completed，模拟已完成的第一个阶段）
    db.add(ResearchStep(
        task_id=task.id,
        step_type="planning",
        status="completed",
        label="Planning：拆解研究主题",
    ))

    # 可选 failed step
    if with_failed_step:
        db.add(ResearchStep(
            task_id=task.id,
            step_type="synthesis",
            status="failed",
            error_code="E3104",
            error_message="LLM 综合失败",
            label="Synthesis：跨源综合",
        ))

    # 可选 completed step
    if with_completed_step:
        db.add(ResearchStep(
            task_id=task.id,
            step_type="search",
            status="completed",
            label="Search：多源搜索",
        ))

    await db.flush()
    return task


class TestRetryTask:
    """断点续跑"""

    # ── 成功路径 ──────────────────────────────────────────────

    async def test_failed任务_recoverable为true_重置为pending并返回resume_from(self, db_session: AsyncSession):
        ec = {
            "last_completed_step_id": "step-search-001",
            "execution_pointer": {"phase": "synthesizing"},
        }
        task = await _seed_retry_task(db_session, status="failed", execution_context=ec, with_failed_step=True)

        result = await retry_task(db_session, task)

        assert result.task_id == task.id
        assert result.status == "pending"
        assert task.status == "pending"
        assert result.resume_from.phase == "synthesizing"
        assert result.resume_from.last_completed_step_id == "step-search-001"
        assert result.resume_from.next_step_type == "evidence_graph"

    async def test_partially_completed任务_可retry(self, db_session: AsyncSession):
        ec = {
            "execution_pointer": {"phase": "fetching"},
        }
        task = await _seed_retry_task(db_session, status="partially_completed", execution_context=ec)

        result = await retry_task(db_session, task)

        assert result.task_id == task.id
        assert result.status == "pending"
        assert result.resume_from.phase == "fetching"
        assert result.resume_from.next_step_type == "rerank"

    async def test_canceled任务_recoverable为true_可retry(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="canceled")

        result = await retry_task(db_session, task)

        assert result.task_id == task.id
        assert result.status == "pending"

    async def test_retry后task_状态为pending_清空错误字段(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="failed", with_failed_step=True)

        await retry_task(db_session, task)

        # 验证 task 的错误字段被清空
        assert task.status == "pending"
        assert task.error_code is None
        assert task.error_message is None
        assert task.recoverable is None
        assert task.completed_at is None
        assert task.current_phase is None

    # ── failed step 重置 ─────────────────────────────────────

    async def test_failed_step_被重置为pending(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="failed", with_failed_step=True)

        await retry_task(db_session, task)

        # 查询 synthesis step 应被重置
        from sqlalchemy import select as sa_sel
        result = await db_session.execute(
            sa_sel(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.step_type == "synthesis",
            )
        )
        failed_steps = result.scalars().all()
        assert len(failed_steps) == 1
        assert failed_steps[0].status == "pending"
        assert failed_steps[0].error_code is None
        assert failed_steps[0].error_message is None

    async def test_completed_step_不被重置(self, db_session: AsyncSession):
        task = await _seed_retry_task(
            db_session, status="failed", with_failed_step=True, with_completed_step=True
        )

        await retry_task(db_session, task)

        # 查询 search step 应保持 completed
        from sqlalchemy import select as sa_sel
        result = await db_session.execute(
            sa_sel(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.step_type == "search",
            )
        )
        search_steps = result.scalars().all()
        assert len(search_steps) == 1
        assert search_steps[0].status == "completed"

    async def test_锁跳过_skipped_主_Step_被重置为pending(self, db_session: AsyncSession):
        """因崩溃遗留幂等锁被跳过的主 Step，retry 时应恢复为 pending。"""
        task = await _seed_retry_task(db_session, status="failed")

        # 因锁被跳过的 rerank 主 Step
        skipped_lock_step = ResearchStep(
            task_id=task.id,
            step_type="rerank",
            parent_step_id=None,
            status="skipped",
            output={"reason": "幂等锁已被占用（可能重复入队）"},
            label="Rerank：来源粗筛精排",
        )
        # 正常跳过的 planning 主 Step，不应被重置
        skipped_normal_step = ResearchStep(
            task_id=task.id,
            step_type="planning",
            parent_step_id=None,
            status="skipped",
            output={"reason": "Phase 函数未注册"},
            label="Planning：拆解研究主题",
        )
        db_session.add_all([skipped_lock_step, skipped_normal_step])
        await db_session.flush()

        # 子 Step 不应被 Orchestrator 调度，保持 skipped
        # 必须先 flush 父 Step 获取 id，再设置 parent_step_id
        skipped_child_step = ResearchStep(
            task_id=task.id,
            step_type="fetch",
            parent_step_id=skipped_lock_step.id,
            status="skipped",
            output={"reason": "幂等锁已被占用（可能重复入队）"},
            label="抓取子步骤",
        )
        db_session.add(skipped_child_step)
        await db_session.flush()

        await retry_task(db_session, task)

        from sqlalchemy import select as sa_sel
        result = await db_session.execute(
            sa_sel(ResearchStep).where(ResearchStep.task_id == task.id)
        )
        steps = {step.id: step for step in result.scalars().all()}

        assert steps[skipped_lock_step.id].status == "pending"
        assert steps[skipped_lock_step.id].output is None

        assert steps[skipped_normal_step.id].status == "skipped"
        assert steps[skipped_normal_step.id].output == {"reason": "Phase 函数未注册"}

        assert steps[skipped_child_step.id].status == "skipped"

    async def test_无failed_step_重置为no_op(self, db_session: AsyncSession):
        """没有 failed step 时 reset 不报错，仅日志记录。"""
        task = await _seed_retry_task(db_session, status="failed")

        # 不应抛异常
        result = await retry_task(db_session, task)
        assert result.status == "pending"

    # ── 错误分支：状态非法 ──────────────────────────────────

    async def test_running任务_抛出E2003(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="running")

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await retry_task(db_session, task)

        assert exc_info.value.error_code == "E2003"
        detail = exc_info.value.error_detail
        assert detail["current_status"] == "running"
        assert set(detail["allowed_statuses"]) == set(RETRY_ALLOWED_STATUSES)

    async def test_completed任务_抛出E2003(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="completed")

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await retry_task(db_session, task)

        assert exc_info.value.error_code == "E2003"
        assert exc_info.value.error_detail["current_status"] == "completed"

    async def test_pending任务_抛出E2003(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="pending")

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await retry_task(db_session, task)

        assert exc_info.value.error_code == "E2003"

    # ── 错误分支：recoverable=false ──────────────────────────

    async def test_recoverable为false_抛出E2003(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="failed", recoverable=False)

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await retry_task(db_session, task)

        assert exc_info.value.error_code == "E2003"

    # ── 错误分支：CAS 冲突 ───────────────────────────────────

    async def test_CAS冲突_状态已变更_抛出E2003(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="failed")

        # 模拟并发：在 retry_task 执行前将 DB 状态改为 completed
        from sqlalchemy import update as sa_update
        await db_session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task.id)
            .values(status="completed")
        )
        await db_session.flush()

        with pytest.raises(TaskStatusConflictException) as exc_info:
            await retry_task(db_session, task)

        assert exc_info.value.error_code == "E2003"

    # ── resume_from 正确性 ───────────────────────────────────

    async def test_resume_from_next_step_type_为最后一个phase时_返回None(self, db_session: AsyncSession):
        """如果 last_phase 是 render（最后一个），next_step_type 应为 None。"""
        ec = {
            "execution_pointer": {"phase": "rendering"},
        }
        task = await _seed_retry_task(db_session, status="failed", execution_context=ec)

        result = await retry_task(db_session, task)

        assert result.resume_from.phase == "rendering"
        assert result.resume_from.next_step_type is None

    async def test_resume_from_execution_context为空时_phase返回None(self, db_session: AsyncSession):
        task = await _seed_retry_task(db_session, status="failed", execution_context=None)

        result = await retry_task(db_session, task)

        assert result.resume_from.phase is None
        assert result.resume_from.last_completed_step_id is None
        assert result.resume_from.next_step_type is None

    async def test_RETRY_ALLOWED_STATUSES_仅含三种状态(self):
        """验证 retry 仅允许 failed / partially_completed / canceled。"""
        assert RETRY_ALLOWED_STATUSES == frozenset({"failed", "partially_completed", "canceled"})


# ═══════════════════════════════════════════════════════════════
# create_task() 意图识别
# ═══════════════════════════════════════════════════════════════


class TestCreateTaskIntent:
    """创建任务时的意图识别门控。"""

    async def test_非研究输入创建direct_answer任务(self, db_session: AsyncSession):
        req = _make_request(topic="你好")
        result = await create_task(db_session, user_id=1, request=req)

        assert result.direct_answer is True
        assert result.status == "completed"
        assert result.report is not None
        assert len(result.report.sections) == 1
        assert result.report.sections[0].heading == "回答"
        assert "ResearchMind" in result.report.sections[0].content

    async def test_研究输入仍走pending流程(self, db_session: AsyncSession):
        req = _make_request(topic="量子计算对密码学的影响")
        result = await create_task(db_session, user_id=1, request=req)

        assert result.direct_answer is False
        assert result.status == "pending"
        assert result.report is None

    async def test_direct_answer任务可被get_report读取(self, db_session: AsyncSession):
        req = _make_request(topic="谢谢")
        result = await create_task(db_session, user_id=1, request=req)

        task = await db_session.get(ResearchTask, result.task_id)
        report_result = await get_report(db_session, task)

        assert report_result.status == "completed"
        assert report_result.report.title == "谢谢"
        assert len(report_result.report.sections) == 1
        assert report_result.evidence_graph["items"] == []
        assert report_result.evidence_graph["sources"] == []
