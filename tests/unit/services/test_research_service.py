"""研究任务 Service 单元测试 — 覆盖 create_task / get_task_list / get_task_detail / delete_task

对齐 TESTING_STRATEGY.md：
- 每个操作成功+失败+所有错误分支独立用例
- 强断言：验证具体值/顺序/错误码
"""

from datetime import datetime, timezone

import pytest
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
    cancel_task,
    create_task,
    get_report,
    get_task_list,
    get_task_detail,
    delete_task,
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
    from app.models.user import User
    from app.core.security import hash_password
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
        assert task.total_steps == 1

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

    async def test_topic超500字符_抛出E2005(self, db_session: AsyncSession):
        """Pydantic 已拦截 >500，此处验证 Pydantic 的拦截。"""
        with pytest.raises(Exception):  # Pydantic ValidationError
            _make_request(topic="研" * 501)

    async def test_topic纯空格_抛出ValidationError(self, db_session: AsyncSession):
        with pytest.raises(Exception):
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
