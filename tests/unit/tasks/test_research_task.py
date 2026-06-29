"""Celery research_task 单元测试 —— _run_pipeline 幂等分支与 _emergency_fail CAS。"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select as sa_select

from app.core.exceptions import SearchFailedException
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.user import User
from app.core.security import hash_password
from app.tasks.research_task import _build_trace_from_steps, _emergency_fail, _run_pipeline


@pytest.fixture(autouse=True)
def _disable_agent_runtime(monkeypatch):
    """本模块测试 PipelineOrchestrator 分支，关闭 Agent Runtime feature flag。"""
    monkeypatch.setattr("app.config.settings.USE_AGENT_RUNTIME", False)


async def _seed_user_and_task(db_session, task_status: str = "pending") -> ResearchTask:
    """创建测试用户与任务。"""
    user = User(
        username="emergency-test-user",
        password_hash=hash_password("pass"),
        role="user",
        status="active",
    )
    db_session.add(user)
    await db_session.flush()

    task = ResearchTask(
        user_id=user.id,
        topic="emergency fail 测试",
        requirements={"task_type": "analysis", "max_sources": 10, "language": "zh"},
        status=task_status,
    )
    db_session.add(task)
    await db_session.flush()
    return task


class _SessionContextManager:
    """把已存在的 db_session 包装成 async_session_factory 的上下文管理器。

    重写 commit 为 flush，避免破坏测试事务隔离。
    """

    def __init__(self, session):
        self._session = session
        # 包装 commit 为 flush，避免 _emergency_fail 提交外层事务
        self._original_commit = session.commit
        session.commit = session.flush

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        self._session.commit = self._original_commit
        return False


def _emergency_fail_session_factory(db_session):
    """返回一个 session_factory，让 _emergency_fail 复用测试 db_session。"""
    def factory():
        return _SessionContextManager(db_session)
    return factory


class TestEmergencyFail:
    """_emergency_fail CAS 与 recoverable 语义测试。"""

    @pytest.mark.asyncio
    async def test_pending任务_CAS更新为failed(self, db_session):
        task = await _seed_user_and_task(db_session, "pending")

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=False)

        assert updated is True
        await db_session.refresh(task)
        assert task.status == "failed"
        assert task.error_code == "E3999"
        # 紧急失败不应暴露原始异常/SQL 等内部细节
        assert "模拟 Worker 崩溃" not in task.error_message
        assert task.error_message == "未预期的内部错误，请稍后重试"
        assert task.recoverable is False
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_running任务_CAS更新为failed(self, db_session):
        task = await _seed_user_and_task(db_session, "running")

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=True)

        assert updated is True
        await db_session.refresh(task)
        assert task.status == "failed"
        assert task.recoverable is True

    @pytest.mark.asyncio
    async def test_completed任务_不被覆盖(self, db_session):
        task = await _seed_user_and_task(db_session, "completed")
        task.completed_at = datetime.now(timezone.utc)
        original_message = task.error_message
        await db_session.flush()

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=False)

        assert updated is False
        await db_session.refresh(task)
        assert task.status == "completed"
        assert task.error_code is None
        assert task.error_message == original_message

    @pytest.mark.asyncio
    async def test_canceled任务_不被覆盖(self, db_session):
        task = await _seed_user_and_task(db_session, "canceled")
        task.completed_at = datetime.now(timezone.utc)
        await db_session.flush()

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=False)

        assert updated is False
        await db_session.refresh(task)
        assert task.status == "canceled"

    @pytest.mark.asyncio
    async def test_保留原异常recoverable语义(self, db_session):
        task = await _seed_user_and_task(db_session, "running")
        original_error = SearchFailedException("Tavily 不可用")

        recoverable = getattr(original_error, "error_detail", {}).get("recoverable", False)
        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), str(original_error), recoverable=recoverable)

        assert updated is True
        await db_session.refresh(task)
        assert task.recoverable is True
        # 即使传入已知异常，紧急失败路径仍使用统一兜底文案，不暴露内部 JSON
        assert task.error_code == "E3999"
        assert task.error_message == "未预期的内部错误，请稍后重试"


# ═══════════════════════════════════════════════════════════════════════
# _run_pipeline 入口三元状态检查
# ═══════════════════════════════════════════════════════════════════════


class TestRunPipelineStatusBranches:
    """_run_pipeline 对 task.status 的三元分支：pending / running / 终态。"""

    @pytest.mark.asyncio
    async def test_pending状态_正常执行(self, db_session):
        task = await _seed_user_and_task(db_session, "pending")

        with patch("app.tasks.research_task.async_session_factory", new=_emergency_fail_session_factory(db_session)):
            with patch("app.tasks.research_task.PipelineOrchestrator") as mock_orch_cls:
                mock_orch = MagicMock()
                mock_orch.run = AsyncMock()
                mock_orch_cls.return_value = mock_orch

                result = await _run_pipeline(str(task.id))

        assert result["status"] == "pending"
        assert result["task_id"] == str(task.id)
        mock_orch.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_running状态_崩溃恢复继续执行(self, db_session):
        task = await _seed_user_and_task(db_session, "running")
        task.started_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await db_session.flush()

        with patch("app.tasks.research_task.async_session_factory", new=_emergency_fail_session_factory(db_session)):
            with patch("app.tasks.research_task.PipelineOrchestrator") as mock_orch_cls:
                mock_orch = MagicMock()
                mock_orch.run = AsyncMock()
                mock_orch_cls.return_value = mock_orch

                result = await _run_pipeline(str(task.id))

        assert result["status"] == "running"
        assert result["task_id"] == str(task.id)
        mock_orch.run.assert_awaited_once()

    @pytest.mark.parametrize("status", ["completed", "failed", "canceled", "partially_completed"])
    @pytest.mark.asyncio
    async def test_终态_跳过执行(self, db_session, status):
        task = await _seed_user_and_task(db_session, status)
        if status == "completed":
            task.completed_at = datetime.now(timezone.utc)
        elif status in ("failed", "canceled"):
            task.completed_at = datetime.now(timezone.utc)
        await db_session.flush()

        with patch("app.tasks.research_task.async_session_factory", new=_emergency_fail_session_factory(db_session)):
            with patch("app.tasks.research_task.PipelineOrchestrator") as mock_orch_cls:
                result = await _run_pipeline(str(task.id))

        assert result["status"] == "skipped"
        assert result["reason"] == f"status={status}"
        mock_orch_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_任务不存在_返回error(self, db_session):
        with patch("app.tasks.research_task.async_session_factory", new=_emergency_fail_session_factory(db_session)):
            with patch("app.tasks.research_task.PipelineOrchestrator") as mock_orch_cls:
                result = await _run_pipeline("00000000-0000-0000-0000-000000000000")

        assert result["status"] == "error"
        assert result["reason"] == "TaskNotFound"
        mock_orch_cls.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# _build_trace_from_steps 退路重建
# ═══════════════════════════════════════════════════════════════════════


class TestBuildTraceFromSteps:
    """从已完成 ResearchStep 重建 previous_trace 的退路逻辑。"""

    @pytest.mark.asyncio
    async def test_从两个已完成步骤重建_phase_durations_ms正确(self, db_session):
        """已完成 planning + search → 重建包含两个阶段的 trace。"""
        task = await _seed_user_and_task(db_session, "running")

        step_plan = ResearchStep(
            task_id=task.id,
            step_type="planning",
            status="completed",
            duration_ms=4500,
            output={"prompt_tokens": 800, "completion_tokens": 200, "model": "gpt-4"},
            cost={"input_tokens": 800, "output_tokens": 200, "estimated_cost_usd": 0.015, "model": "gpt-4"},
        )
        step_search = ResearchStep(
            task_id=task.id,
            step_type="search",
            status="completed",
            duration_ms=3200,
            output={"total_results": 50, "search_cost_usd": 0.05},
            cost={"estimated_cost_usd": 0.05},
        )
        db_session.add_all([step_plan, step_search])
        await db_session.flush()

        trace = await _build_trace_from_steps(db_session, str(task.id))

        assert trace is not None
        assert "phases" in trace
        assert "phase_durations_ms" in trace

        phases = trace["phases"]
        assert "planning" in phases
        assert "search" in phases
        assert phases["planning"]["duration_ms"] == 4500
        assert phases["planning"]["input_tokens"] == 800
        assert phases["planning"]["output_tokens"] == 200
        assert phases["planning"]["model"] == "gpt-4"
        assert phases["search"]["duration_ms"] == 3200
        assert phases["search"]["cost_usd"] == 0.05

        assert trace["phase_durations_ms"]["planning"] == 4500
        assert trace["phase_durations_ms"]["search"] == 3200

    @pytest.mark.asyncio
    async def test_无已完成步骤_返回None(self, db_session):
        """没有已完成/跳过步骤时返回 None。"""
        task = await _seed_user_and_task(db_session, "running")

        trace = await _build_trace_from_steps(db_session, str(task.id))
        assert trace is None

    @pytest.mark.asyncio
    async def test_同一阶段多条记录_保留耗时最长(self, db_session):
        """fetch 阶段有多条 step 记录时，保留 duration_ms 最大的一条。"""
        task = await _seed_user_and_task(db_session, "running")

        # 主 step（耗时最长）
        step_main = ResearchStep(
            task_id=task.id,
            step_type="fetch",
            status="completed",
            duration_ms=15000,
            output={"fetched": [], "successful": 10, "fetch_cost_usd": 0.10},
        )
        # 子 step（耗时较短，会被过滤）
        step_child = ResearchStep(
            task_id=task.id,
            step_type="fetch",
            status="completed",
            duration_ms=1200,
            output={"url": "https://example.com/1", "content_length": 5000},
        )
        db_session.add_all([step_main, step_child])
        await db_session.flush()

        trace = await _build_trace_from_steps(db_session, str(task.id))

        assert trace is not None
        phases = trace["phases"]
        assert "fetch" in phases
        # 保留耗时最长的（主 step）
        assert phases["fetch"]["duration_ms"] == 15000
        assert phases["fetch"]["cost_usd"] == 0.10

    @pytest.mark.asyncio
    async def test_cost_usd取自step_cost字段(self, db_session):
        """output 中无 cost_usd 时，回退到 cost 字段。"""
        task = await _seed_user_and_task(db_session, "running")

        step = ResearchStep(
            task_id=task.id,
            step_type="search",
            status="completed",
            duration_ms=2500,
            output={"total_results": 30},
            cost={"estimated_cost_usd": 0.03},
        )
        db_session.add(step)
        await db_session.flush()

        trace = await _build_trace_from_steps(db_session, str(task.id))

        assert trace is not None
        assert trace["phases"]["search"]["cost_usd"] == 0.03

    @pytest.mark.asyncio
    async def test_skipped状态也会被重建(self, db_session):
        """skipped 状态的 step 也被纳入重建（前端仍需展示）。"""
        task = await _seed_user_and_task(db_session, "running")

        step = ResearchStep(
            task_id=task.id,
            step_type="evidence_graph",
            status="skipped",
            duration_ms=100,
            output={"evidence_count": 15, "source_count": 8},
        )
        db_session.add(step)
        await db_session.flush()

        trace = await _build_trace_from_steps(db_session, str(task.id))

        assert trace is not None
        assert "evidence_graph" in trace["phases"]
        assert trace["phases"]["evidence_graph"]["duration_ms"] == 100

    @pytest.mark.asyncio
    async def test_token取自output优先于cost(self, db_session):
        """output 和 cost 都有 token 数据时，output 优先。"""
        task = await _seed_user_and_task(db_session, "running")

        step = ResearchStep(
            task_id=task.id,
            step_type="render",
            status="completed",
            duration_ms=28000,
            output={"prompt_tokens": 10000, "completion_tokens": 6000, "model": "gpt-4"},
            cost={"input_tokens": 5000, "output_tokens": 3000, "model": "gpt-3.5-turbo"},
        )
        db_session.add(step)
        await db_session.flush()

        trace = await _build_trace_from_steps(db_session, str(task.id))

        assert trace is not None
        phase = trace["phases"]["render"]
        assert phase["input_tokens"] == 10000  # output 优先
        assert phase["output_tokens"] == 6000
        assert phase["model"] == "gpt-4"  # output 优先
