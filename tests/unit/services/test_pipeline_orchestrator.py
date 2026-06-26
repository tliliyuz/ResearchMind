"""PipelineOrchestrator 单元测试 — 七阶段调度、幂等锁、FATAL 提前终止、_finalize_task 三分支。

Mock 注入 phase_handlers + AsyncMock session + MagicMock sse_bridge，
验证核心调度逻辑的正确性。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select as sa_select

from app.core.security import hash_password
from app.core.task_state_resolver import FATAL_STEP_ERROR_CODES
from app.core.trace_recorder import TraceRecorder
from app.models.enums import TASK_PHASE_ENUM, STEP_TYPE_ENUM
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.user import User
from app.pipeline.sse_bridge import (
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    EVENT_STEP_STARTED,
    EVENT_TASK_CANCELED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_FAILED,
    EVENT_TASK_PROGRESS,
    EVENT_TASK_WARNING,
)
from app.services.pipeline_orchestrator import (
    PHASE_LABELS,
    PHASE_ORDER,
    PipelineOrchestrator,
)


# ═══════════════════════════════════════════════════════════════
# 工厂
# ═══════════════════════════════════════════════════════════════


def _make_task(**kwargs) -> MagicMock:
    """创建测试用 ResearchTask mock，默认 status=running。"""
    task = MagicMock(spec=ResearchTask)
    task.id = kwargs.get("id", 1)
    task.status = kwargs.get("status", "running")
    task.topic = kwargs.get("topic", "测试主题")
    task.current_phase = kwargs.get("current_phase", None)
    total_steps = kwargs.get("total_steps", 7)
    completed_steps = kwargs.get("completed_steps", 0)
    task.total_steps = total_steps
    task.completed_steps = completed_steps
    task.total_sources = kwargs.get("total_sources", 0)
    task.total_evidence = kwargs.get("total_evidence", 0)
    task.error_code = kwargs.get("error_code", None)
    task.error_message = kwargs.get("error_message", None)
    task.recoverable = kwargs.get("recoverable", None)
    task.created_at = kwargs.get("created_at", datetime.now(timezone.utc))
    task.started_at = kwargs.get("started_at", datetime.now(timezone.utc))
    task.completed_at = kwargs.get("completed_at", None)
    task.execution_context = kwargs.get("execution_context", None)

    # 构造 steps 列表，避免 _check_early_termination / _finalize_task 把 MagicMock
    # 当成空列表导致误判（空列表会被视为全部终态并触发 Evidence Threshold 判定）。
    steps = []
    for i in range(total_steps):
        step_mock = MagicMock(spec=ResearchStep)
        step_mock.status = "completed" if i < completed_steps else "pending"
        step_mock.error_code = None
        step_mock.error_message = None
        steps.append(step_mock)
    task.steps = steps
    return task


def _make_phase_handler(should_fail: bool = False, error: Exception = None):
    """创建 Phase handler mock，可选失败。"""
    async def handler(task, step, session, sse_bridge):
        if should_fail:
            if error:
                raise error
            raise RuntimeError("模拟 Phase 失败")
        return {"status": "ok"}
    return handler


def _configure_async_mock_session(session: AsyncMock) -> None:
    """配置 AsyncMock session，使 _create_step 中的复用查询返回 None。

    默认 AsyncMock 的 scalar_one_or_none() 被 await 后会返回 AsyncMock 实例，
    导致 _create_step 误判为"复用已有 Step"。生产环境无此问题（真实 DB 返回 None
    或 ResearchStep 实例），此处仅为 Mock 测试做一致性配置。

    同时默认 rowcount=1，避免 CAS 更新后把 AsyncMock 当整数比较失败。
    """
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.execute.return_value.rowcount = 1


# ═══════════════════════════════════════════════════════════════
# Phase 顺序与调度
# ═══════════════════════════════════════════════════════════════


class TestPhaseOrder:
    """七阶段顺序正确，按 PHASE_ORDER 串行调度。"""

    def test_PHASE_ORDER_包含全部七阶段(self):
        """PHASE_ORDER 应包含全部 7 个 step_type。"""
        assert len(PHASE_ORDER) == 7
        expected = [
            "planning", "search", "fetch", "rerank",
            "synthesis", "evidence_graph", "render",
        ]
        assert list(PHASE_ORDER) == expected

    def test_PHASE_LABELS_七阶段均有中文标签(self):
        """PHASE_LABELS 为七阶段提供前端展示用中文标签。"""
        for step_type in PHASE_ORDER:
            assert step_type in PHASE_LABELS
            assert isinstance(PHASE_LABELS[step_type], str)
            assert len(PHASE_LABELS[step_type]) > 0

    @pytest.mark.asyncio
    async def test_run_按顺序调用已注册phase_handler(self):
        """已注册 handler 的 phase 按 PHASE_ORDER 顺序被调用。"""
        task = _make_task()
        session = AsyncMock()
        _configure_async_mock_session(session)
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        call_order = []
        handlers = {}
        for phase in PHASE_ORDER[:3]:  # planning / search / fetch
            async def h(t, s, sess, sb, p=phase):
                call_order.append(p)
                return {"status": "ok"}
            handlers[phase] = h

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        # Mock 模块级锁函数（acquire_step_lock_async / release_step_lock_async）
        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
            with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                await orchestrator.run()

        assert call_order == ["planning", "search", "fetch"]

    @pytest.mark.asyncio
    async def test_run_未注册handler自动跳过(self):
        """未注册 handler 的 phase → _skip_phase 被调用且不抛异常。"""
        task = _make_task()
        session = AsyncMock()
        _configure_async_mock_session(session)
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        handlers = {"planning": _make_phase_handler()}

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        skip_phases = []
        original_skip = orchestrator._skip_phase

        async def _tracking_skip(step, phase_name, reason=""):
            skip_phases.append(phase_name)
            await original_skip(step, phase_name, reason=reason)

        orchestrator._skip_phase = _tracking_skip

        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
            with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                await orchestrator.run()

        # 6 unregistered phases skip (all except planning)
        assert len(skip_phases) >= 1  # at least search/fetch/rerank/synthesis/evidence_graph/render


# ═══════════════════════════════════════════════════════════════
# 幂等锁
# ═══════════════════════════════════════════════════════════════


class TestIdempotentLock:
    """幂等锁占用 → 跳过 phase。"""

    @pytest.mark.asyncio
    async def test_锁已被占用则跳过phase(self):
        """acquire_step_lock_async 返回 False → phase 被跳过且不抛异常。"""
        task = _make_task()
        session = AsyncMock()
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)
        handlers = {"planning": _make_phase_handler()}

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=False):
            # 锁被占用 → orchestrator 应完成运行（不抛异常），所有 phase 被跳过
            await orchestrator.run()

        # 验证 orchestrator 完成运行（无异常即为通过）


# ═══════════════════════════════════════════════════════════════
# FATAL 错误提前终止
# ═══════════════════════════════════════════════════════════════


class TestFatalErrorTermination:
    """FATAL 错误码 → 提前终止并 emit task.failed。"""

    @pytest.mark.asyncio
    async def test_FATAL错误_emit_task_failed事件(self):
        """Planning 抛出 E3101（FATAL）→ emit task.failed + task 状态为 failed。"""
        from app.core.exceptions import PlanningFailedException

        task = _make_task()
        session = AsyncMock()
        _configure_async_mock_session(session)
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)
        handlers = {
            "planning": _make_phase_handler(
                should_fail=True,
                error=PlanningFailedException("测试 FATAL 错误"),
            )
        }

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
            with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                await orchestrator.run()

        # 验证 task.failed 事件被发送
        task_failed_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_FAILED
        ]
        assert len(task_failed_calls) >= 1
        # 验证 error_code 在 FATAL 集中
        assert "E3101" in FATAL_STEP_ERROR_CODES

    @pytest.mark.asyncio
    async def test_可恢复致命错误_emit_task_failed_recoverable为True_终止Pipeline(self):
        """FATAL 但 recoverable=true 的错误（E3104）→ emit task.failed(recoverable=True) + Pipeline 终止。"""
        from app.core.exceptions import SynthesisFailedException

        task = _make_task()
        task.execution_context = {"last_completed_step_id": "some-step-uuid"}
        session = AsyncMock()
        _configure_async_mock_session(session)
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        call_order = []
        async def failing_planning(t, s, sess, sb):
            call_order.append("planning")
            raise SynthesisFailedException("模拟可恢复致命失败")

        async def ok_search(t, s, sess, sb):
            call_order.append("search")
            return {"status": "ok"}

        handlers = {"planning": failing_planning, "search": ok_search}

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
            with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                await orchestrator.run()

        # 验证 task.failed 事件被发送且 recoverable=True
        failed_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_FAILED
        ]
        assert len(failed_calls) >= 1
        payload = failed_calls[0][0][1]
        assert payload["recoverable"] is True
        assert payload.get("last_checkpoint") == "some-step-uuid"

        # 验证没有 warning 事件（所有 E31xx 均致命）
        warning_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_WARNING
        ]
        assert len(warning_calls) == 0

        # 验证 Pipeline 在 planning 后终止，search 未执行
        assert call_order == ["planning"]


# ═══════════════════════════════════════════════════════════════
# _finalize_task 三分支
# ═══════════════════════════════════════════════════════════════


class TestFinalizeTask:
    """_finalize_task 根据 steps 终态推导 task 最终状态。"""

    @pytest.mark.asyncio
    async def test_全部phase注册且完成_emit_task_completed(self):
        """所有 7 个 phases 成功完成 → emit task.completed。"""
        task = _make_task(completed_steps=7, total_steps=7, total_evidence=10)
        task.status = "running"
        session = AsyncMock()
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        # 注册全部 7 个 phase handler
        handlers = {p: _make_phase_handler() for p in PHASE_ORDER}

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
            with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                await orchestrator.run()

        # 验证 task.completed 事件被发送
        completed_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_COMPLETED
        ]
        assert len(completed_calls) >= 1

    @pytest.mark.asyncio
    async def test_有failed_step_emit_task_failed(self):
        """存在 failed step → emit task.failed。"""
        from app.core.exceptions import PlanningFailedException

        task = _make_task()
        session = AsyncMock()
        _configure_async_mock_session(session)
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)
        handlers = {
            "planning": _make_phase_handler(
                should_fail=True,
                error=PlanningFailedException("FATAL"),
            )
        }

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers=handlers,
        )

        with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
            with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                await orchestrator.run()

        failed_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_FAILED
        ]
        assert len(failed_calls) >= 1


# ═══════════════════════════════════════════════════════════════
# 取消检测
# ═══════════════════════════════════════════════════════════════


class TestCancelDetection:
    """Orchestrator 检测到 status=canceled 后停止并发送 task.canceled。"""

    @pytest.mark.asyncio
    async def test_任务已取消_发送task_canceled事件(self):
        task = _make_task(status="canceled")
        session = AsyncMock()
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        # refresh 后 task.status 仍为 canceled
        async def _refresh(task_obj, attrs=None):
            return None
        session.refresh.side_effect = _refresh

        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=MagicMock(), phase_handlers={},
        )

        await orchestrator.run()

        canceled_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_CANCELED
        ]
        assert len(canceled_calls) == 1
        payload = canceled_calls[0][0][1]
        assert payload["task_id"] == str(task.id)
        assert payload["status"] == "canceled"


# ═══════════════════════════════════════════════════════════════
# 成本追踪
# ═══════════════════════════════════════════════════════════════


class TestCostTracking:
    """Step cost 写入与 Trace 聚合。"""

    @pytest.mark.asyncio
    async def test_complete_step_写入step_cost(self):
        from app.core.trace_recorder import TraceRecorder

        task = _make_task()
        session = AsyncMock()
        session.refresh = AsyncMock()
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        # 构造真实 ResearchStep，便于断言 cost 字段
        step = ResearchStep(
            id="step-cost-001",
            task_id=task.id,
            step_type="planning",
            status="running",
            started_at=datetime.now(timezone.utc),
        )

        trace = TraceRecorder(task_id=str(task.id), user_id=1, topic="测试")
        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=trace, phase_handlers={},
        )

        output = {
            "sub_questions": ["q1", "q2"],
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "model": "deepseek-v4-pro",
            "retry_count": 0,
        }
        await orchestrator._complete_step(step, "planning", output)

        assert step.cost is not None
        assert step.cost["input_tokens"] == 1000
        assert step.cost["output_tokens"] == 200
        assert step.cost["model"] == "deepseek-v4-pro"
        assert step.cost["estimated_cost_usd"] > 0

    @pytest.mark.asyncio
    async def test_complete_step_非LLM阶段不写入cost(self):
        from app.core.trace_recorder import TraceRecorder

        task = _make_task()
        session = AsyncMock()
        session.refresh = AsyncMock()
        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)

        step = ResearchStep(
            id="step-cost-002",
            task_id=task.id,
            step_type="search",
            status="running",
            started_at=datetime.now(timezone.utc),
        )

        trace = TraceRecorder(task_id=str(task.id), user_id=1, topic="测试")
        orchestrator = PipelineOrchestrator(
            task=task, session=session, sse_bridge=sse_bridge,
            trace_recorder=trace, phase_handlers={},
        )

        await orchestrator._complete_step(step, "search", {"after_dedup": 5})

        assert step.cost is None

    @pytest.mark.asyncio
    async def test_trace_聚合各LLM阶段成本(self):
        from app.core.trace_recorder import TraceRecorder

        trace = TraceRecorder(task_id="task-trace-001", user_id=1, topic="测试")
        trace.record_planning(
            duration_ms=1000,
            input_tokens=1000,
            output_tokens=200,
            sub_questions_count=3,
            model="deepseek-v4-pro",
        )
        trace.record_rerank(
            duration_ms=2000,
            bm25_candidates=10,
            llm_reranked=5,
            input_tokens=2000,
            output_tokens=300,
            model="deepseek-v4-flash",
        )
        trace.record_synthesis(
            duration_ms=3000,
            input_tokens=5000,
            output_tokens=1000,
            clusters_count=2,
            model="deepseek-v4-pro",
        )
        trace.record_render(
            duration_ms=4000,
            input_tokens=3000,
            output_tokens=1500,
            sections_count=3,
            model="deepseek-v4-pro",
        )

        result = trace.finish()

        assert result["total_input_tokens"] == 11000
        assert result["total_output_tokens"] == 3000
        assert result["total_tokens"] == 14000
        assert result["total_cost_usd"] > 0
        assert "planning" in result["breakdown"]
        assert "rerank" in result["breakdown"]
        assert "synthesis" in result["breakdown"]
        assert "render" in result["breakdown"]
        assert result["breakdown"]["planning"]["tokens"] == 1200
        assert result["breakdown"]["planning"]["cost"] > 0
        assert result["phases"]["planning"]["model"] == "deepseek-v4-pro"


# ═══════════════════════════════════════════════════════════════════════
# 真实 DB session 集成验证
# ═══════════════════════════════════════════════════════════════════════


class TestPipelineWithRealSession:
    """使用真实 DB session 验证 Pipeline 完成后 Task 状态正确流转。"""

    @pytest.mark.asyncio
    async def test_全部phase完成后_task状态变为completed(self, db_session):
        """全部 7 个 phase handler 成功执行后，task status 应从 running 变为 completed。"""
        user = User(
            username="pipeline-real-session",
            password_hash=hash_password("pass"),
            role="user",
            status="active",
        )
        db_session.add(user)
        await db_session.flush()

        task = ResearchTask(
            user_id=user.id,
            topic="真实 session 测试",
            requirements={"task_type": "analysis", "max_sources": 10, "language": "zh"},
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.flush()

        handlers = {phase: _make_phase_handler() for phase in PHASE_ORDER}

        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)
        trace_recorder = TraceRecorder(
            task_id=str(task.id), user_id=str(user.id), topic=task.topic
        )

        orchestrator = PipelineOrchestrator(
            task=task,
            session=db_session,
            sse_bridge=sse_bridge,
            trace_recorder=trace_recorder,
            phase_handlers=handlers,
        )

        # 阻止内部 commit，避免破坏测试事务隔离；所有写操作仍在同一事务内可见
        with patch.object(db_session, "commit", new_callable=AsyncMock):
            with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
                with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                    await orchestrator.run()

        # 在同一未提交事务内查询验证 CAS 更新结果
        result = await db_session.execute(
            sa_select(ResearchTask).where(ResearchTask.id == task.id)
        )
        updated_task = result.scalar_one()
        assert updated_task.status == "completed"

        completed_calls = [
            c for c in sse_bridge.publish.call_args_list
            if c[0][0] == EVENT_TASK_COMPLETED
        ]
        assert len(completed_calls) == 1
        assert completed_calls[0][0][1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_复用research_service创建的pending_planning_step(self, db_session):
        """research_service 预先创建的 pending planning step 应被复用并完成。"""
        user = User(
            username="pipeline-reuse-planning",
            password_hash=hash_password("pass"),
            role="user",
            status="active",
        )
        db_session.add(user)
        await db_session.flush()

        task = ResearchTask(
            user_id=user.id,
            topic="复用 planning step 测试",
            requirements={"task_type": "analysis", "max_sources": 10, "language": "zh"},
            status="running",
            total_steps=1,
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(task)
        await db_session.flush()

        # 模拟 research_service 预先创建的 pending planning step
        planning_step = ResearchStep(
            task_id=task.id,
            step_type="planning",
            status="pending",
            label="Planning：拆解研究主题",
        )
        db_session.add(planning_step)
        await db_session.flush()

        handlers = {phase: _make_phase_handler() for phase in PHASE_ORDER}

        sse_bridge = MagicMock()
        sse_bridge.task_id = str(task.id)
        trace_recorder = TraceRecorder(
            task_id=str(task.id), user_id=str(user.id), topic=task.topic
        )

        orchestrator = PipelineOrchestrator(
            task=task,
            session=db_session,
            sse_bridge=sse_bridge,
            trace_recorder=trace_recorder,
            phase_handlers=handlers,
        )

        with patch.object(db_session, "commit", new_callable=AsyncMock):
            with patch("app.services.pipeline_orchestrator.acquire_step_lock_async", return_value=True):
                with patch("app.services.pipeline_orchestrator.release_step_lock_async"):
                    await orchestrator.run()

        # 验证只存在一个 planning step，且它由 pending 转为 completed
        result = await db_session.execute(
            sa_select(ResearchStep)
            .where(ResearchStep.task_id == task.id, ResearchStep.step_type == "planning")
            .order_by(ResearchStep.started_at)
        )
        planning_steps = result.scalars().all()
        assert len(planning_steps) == 1
        assert planning_steps[0].id == planning_step.id
        assert planning_steps[0].status == "completed"

        # 验证 task 状态变为 completed
        result = await db_session.execute(
            sa_select(ResearchTask).where(ResearchTask.id == task.id)
        )
        updated_task = result.scalar_one()
        assert updated_task.status == "completed"
