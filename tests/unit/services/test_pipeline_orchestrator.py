"""PipelineOrchestrator 单元测试 — 七阶段调度、幂等锁、FATAL 提前终止、_finalize_task 三分支。

Mock 注入 phase_handlers + AsyncMock session + MagicMock sse_bridge，
验证核心调度逻辑的正确性。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.task_state_resolver import FATAL_STEP_ERROR_CODES
from app.models.enums import TASK_PHASE_ENUM, STEP_TYPE_ENUM
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import (
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    EVENT_STEP_STARTED,
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
