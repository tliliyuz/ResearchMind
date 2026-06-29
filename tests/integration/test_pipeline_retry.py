"""Phase4 Pipeline 断点续跑集成测试。

覆盖场景：
- 已完成任务 Retry 所有阶段跳过
- Synthesis / Render / Search 失败后 Retry
- Worker 崩溃后恢复（Synthesis 前 / Fetch 阶段 / Planning 阶段）
- Evidence 只追加不覆盖
- completed_steps / progress 恢复后正确
- Retry API 前置校验
- SSE 事件序列完整性
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.core.trace_recorder import TraceRecorder
from app.models.evidence_item import EvidenceItem
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import (
    EVENT_CHECKPOINT_SAVED,
    EVENT_PHASE_COMPLETED,
    EVENT_PHASE_STARTED,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_STARTED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_CREATED,
    EVENT_TASK_FAILED,
    EVENT_TASK_PROGRESS,
    SSEBridge,
)
from app.services.pipeline_orchestrator import PipelineOrchestrator, build_default_phase_handlers
from app.services.research_service import retry_task
from app.tasks.research_task import _run_pipeline

from tests.integration._retry_helpers import (
    PHASE_LABELS,
    PHASE_ORDER,
    _assert_evidence_count,
    _assert_main_step_status,
    _assert_report_sections_exist,
    _assert_sources_count,
    _commit_to_flush,
    _get_task,
    _mock_pipeline_external,
    _record_sse_events,
    _seed_crash_task,
    _seed_failed_task,
    _seed_task,
    _session_factory,
)


pytestmark = [pytest.mark.integration, pytest.mark.retry]


@pytest.fixture(autouse=True)
def _disable_agent_runtime(monkeypatch):
    """Pipeline retry 集成测试针对 PipelineOrchestrator，关闭 Agent Runtime feature flag。"""
    monkeypatch.setattr("app.config.settings.USE_AGENT_RUNTIME", False)


# ═══════════════════════════════════════════════════════════════
# 1. 已完成任务 Retry：所有阶段跳过
# ═══════════════════════════════════════════════════════════════


class TestPipelineRetryFullFlow:
    """任务已完成后的 Retry 集成测试。"""

    @pytest.mark.asyncio
    async def test_已完成任务_retry_所有阶段跳过_状态保持completed(self, db_session):
        """completed 任务 retry 后，7 个 phase handler 不被调用，task.status 仍为 completed。"""
        task = await _seed_failed_task(
            db_session,
            completed_through="render",
            failed_at="render",
            recoverable=True,
            error_code="E3107",
        )
        # 修正为 completed 状态，模拟真实已完成任务
        task.status = "completed"
        task.error_code = None
        task.error_message = None
        task.recoverable = None
        await db_session.flush()

        handler_calls = {step_type: 0 for step_type in PHASE_ORDER}
        original_handlers = build_default_phase_handlers()

        async def _counting_handler(step_type: str):
            async def _wrapper(*args, **kwargs):
                handler_calls[step_type] += 1
                return await original_handlers[step_type](*args, **kwargs)
            return _wrapper

        counting_handlers = {
            step_type: await _counting_handler(step_type)
            for step_type in PHASE_ORDER
        }

        sse_bridge = SSEBridge(task.id)
        published = _record_sse_events(sse_bridge)
        trace = TraceRecorder(task_id=task.id, user_id=1, topic=task.topic, previous_trace=task.trace)

        patches = _mock_pipeline_external(db_session, task.id)
        async with _commit_to_flush(db_session):
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                orchestrator = PipelineOrchestrator(
                    task=task,
                    session=db_session,
                    sse_bridge=sse_bridge,
                    trace_recorder=trace,
                    phase_handlers=counting_handlers,
                )
                await orchestrator.run()

        # 验证：所有 phase handler 未被调用（因为所有 step 已是 completed）
        assert sum(handler_calls.values()) == 0
        # 任务保持 completed
        assert task.status == "completed"
        # SSE 不应发送 task.created（running 路径不发送，但 completed 进入 _start_task 会返回 False）
        assert all(e[0] != EVENT_TASK_CREATED for e in published)


# ═══════════════════════════════════════════════════════════════
# 2. 失败恢复场景
# ═══════════════════════════════════════════════════════════════


class TestPipelineRetryFromFailure:
    """任务失败后 Retry 的集成测试。"""

    @pytest.mark.asyncio
    async def test_synthesis失败后retry_复用前四阶段并完成报告(self, db_session):
        """Synthesis 失败后 Retry，planning/search/fetch/rerank 复用，synthesis 重新执行。"""
        task = await _seed_failed_task(
            db_session,
            completed_through="rerank",
            failed_at="synthesis",
            recoverable=True,
            error_code="E3104",
        )

        # 记录复用前 Step ID
        prev_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        prev_step_ids = {s.step_type: str(s.id) for s in prev_steps.scalars().all()}

        # 调用 retry_task 重置状态
        await retry_task(db_session, task)
        await db_session.flush()
        assert task.status == "pending"

        # 调用 _run_pipeline 实际执行（patch async_session_factory 复用测试 session）
        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        # 验证主 Step 状态
        await _assert_main_step_status(
            db_session,
            task.id,
            {
                "planning": "completed",
                "search": "completed",
                "fetch": "completed",
                "rerank": "completed",
                "synthesis": "completed",
                "evidence_graph": "completed",
                "render": "completed",
            },
        )

        # 验证前 4 阶段 Step 被复用（ID 不变）
        current_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        current_step_ids = {s.step_type: str(s.id) for s in current_steps.scalars().all()}
        for phase in PHASE_ORDER[:4]:
            assert current_step_ids[phase] == prev_step_ids[phase], f"{phase} Step 未被复用"

        # 验证报告已产出
        await _assert_report_sections_exist(db_session, task.id, expected_count=3)

        # 验证 Trace 连续性：前 4 阶段数据保留，后 3 阶段数据新增
        refreshed_task = await _get_task(db_session, task.id)
        trace = refreshed_task.trace
        assert trace is not None
        for phase in PHASE_ORDER:
            assert trace["phases"][phase] is not None, f"Trace 缺少 {phase} 阶段"
        # 前 4 阶段 duration_ms 应为预置的 1000（来自 previous_trace）
        for phase in PHASE_ORDER[:4]:
            assert trace["phases"][phase]["duration_ms"] == 1000
        # 总计 token 应包含前 4 阶段 + 后 3 阶段
        assert trace["total_input_tokens"] >= 400
        assert trace["total_output_tokens"] >= 200

    @pytest.mark.asyncio
    async def test_render失败后retry_复用evidence_graph并重新渲染(self, db_session):
        """Render 失败后 Retry，evidence_graph 复用，render 重新执行。"""
        task = await _seed_failed_task(
            db_session,
            completed_through="evidence_graph",
            failed_at="render",
            recoverable=True,
            error_code="E3107",
        )

        prev_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        prev_step_ids = {s.step_type: str(s.id) for s in prev_steps.scalars().all()}

        await retry_task(db_session, task)
        await db_session.flush()

        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        await _assert_main_step_status(
            db_session,
            task.id,
            {
                "planning": "completed",
                "search": "completed",
                "fetch": "completed",
                "rerank": "completed",
                "synthesis": "completed",
                "evidence_graph": "completed",
                "render": "completed",
            },
        )

        # evidence_graph Step 应被复用；render Step 被重置为 pending 后重新执行完成
        current_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        current_step_ids = {s.step_type: str(s.id) for s in current_steps.scalars().all()}
        assert current_step_ids["evidence_graph"] == prev_step_ids["evidence_graph"]
        assert current_step_ids["render"] == prev_step_ids["render"]

        await _assert_report_sections_exist(db_session, task.id, expected_count=3)

    @pytest.mark.asyncio
    async def test_search完全失败后retry_仅重新执行search及后续阶段(self, db_session):
        """Search 阶段完全失败后 Retry，planning 复用，search 及后续重新执行。"""
        task = await _seed_failed_task(
            db_session,
            completed_through="planning",
            failed_at="search",
            recoverable=True,
            error_code="E3102",
        )

        prev_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        prev_step_ids = {s.step_type: str(s.id) for s in prev_steps.scalars().all()}

        await retry_task(db_session, task)
        await db_session.flush()

        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        await _assert_main_step_status(
            db_session,
            task.id,
            {
                "planning": "completed",
                "search": "completed",
                "fetch": "completed",
                "rerank": "completed",
                "synthesis": "completed",
                "evidence_graph": "completed",
                "render": "completed",
            },
        )

        # planning Step 复用
        current_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        current_step_ids = {s.step_type: str(s.id) for s in current_steps.scalars().all()}
        assert current_step_ids["planning"] == prev_step_ids["planning"]

        await _assert_sources_count(db_session, task.id, expected=4)
        await _assert_evidence_count(db_session, task.id, expected=4)


# ═══════════════════════════════════════════════════════════════
# 3. Worker 崩溃恢复场景
# ═══════════════════════════════════════════════════════════════


class TestCrashRecovery:
    """Worker 崩溃后恢复的集成测试。"""

    @pytest.mark.asyncio
    async def test_worker在synthesis前崩溃_恢复后trace完整(self, db_session):
        """Worker 在 Synthesis 前崩溃，恢复后 Trace 包含全部 7 阶段且数据连续。"""
        task = await _seed_crash_task(db_session, crash_after="rerank")

        prev_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        prev_step_ids = {s.step_type: str(s.id) for s in prev_steps.scalars().all()}

        # 直接使用 _run_pipeline 走崩溃恢复路径
        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        # synthesis Step 应被复用（running 状态残留）
        current_steps = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.parent_step_id.is_(None),
            )
        )
        current_step_ids = {s.step_type: str(s.id) for s in current_steps.scalars().all()}
        assert current_step_ids["synthesis"] == prev_step_ids["synthesis"]

        refreshed_task = await _get_task(db_session, task.id)
        trace = refreshed_task.trace
        assert trace is not None

        # 所有阶段都应有数据
        for phase in PHASE_ORDER:
            assert trace["phases"][phase] is not None, f"Trace 缺少 {phase}"

        # 前 4 阶段应保留 previous_trace 的 duration_ms=5000
        for phase in PHASE_ORDER[:4]:
            assert trace["phases"][phase]["duration_ms"] == 5000

        # token 累计应包含前 4 阶段 + 后 3 阶段
        assert trace["total_input_tokens"] >= 400
        assert trace["total_output_tokens"] >= 200

    @pytest.mark.asyncio
    async def test_worker在fetch阶段崩溃_超时监察者标记后可retry恢复(self, db_session):
        """Worker 在 Fetch 阶段崩溃，超时监察者标记 E3112，Retry 后恢复完成。"""
        from app import main as main_module

        task = await _seed_crash_task(db_session, crash_after="search", started_seconds_ago=120)
        # 确保 fetch 阶段为 running（模拟崩溃残留）
        fetch_step = await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.step_type == "fetch",
                ResearchStep.parent_step_id.is_(None),
            )
        )
        fetch_step = fetch_step.scalar_one_or_none()
        assert fetch_step is not None
        fetch_step.status = "running"
        await db_session.flush()

        main_module._worker_lock_missing_since.clear()

        # 第一次超时扫描：记录缺失时间
        with patch("app.main.async_session_factory", new=_session_factory(db_session)):
            with patch("app.main.check_task_lock_async", new_callable=AsyncMock, return_value=False):
                with patch("app.main.settings.WORKER_TIMEOUT_SECONDS", 0):
                    from app.main import _check_worker_timeouts

                    async with _commit_to_flush(db_session):
                        await _check_worker_timeouts()
                        # 第二次扫描立即触发标记
                        await _check_worker_timeouts()

        refreshed = await _get_task(db_session, task.id)
        assert refreshed.status == "failed"
        assert refreshed.error_code == "E3112"
        assert refreshed.recoverable is True

        # Retry 并恢复（使用最新加载的 task 对象，避免跨 commit 后的对象过期问题）
        await retry_task(db_session, refreshed)
        await db_session.flush()
        await db_session.refresh(refreshed)
        assert refreshed.status == "pending"

        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        await _assert_main_step_status(
            db_session,
            task.id,
            {phase: "completed" for phase in PHASE_ORDER},
        )

    @pytest.mark.asyncio
    async def test_worker在planning阶段崩溃_从steps重建trace并恢复(self, db_session):
        """首个 checkpoint 前崩溃，task.trace 为空，从 research_steps 重建 minimal trace。"""
        task = await _seed_task(
            db_session,
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
        )
        # 创建 planning completed step（有 completed_at 但 task.trace 为空）
        now = datetime.now(timezone.utc)
        from tests.integration._retry_helpers import _create_step
        planning_step = await _create_step(
            db_session,
            task.id,
            "planning",
            status="completed",
            output={
                "sub_questions": [
                    "量子计算对 RSA/ECC 的具体威胁",
                    "NIST 后量子密码标准化最新进展",
                    "中国在量子安全通信领域的政策与布局",
                ],
                "rationale": "从技术威胁、标准应对、政策布局三维度拆解",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "model": "gpt-4o-mini",
            },
            started_at=now - timedelta(seconds=100),
            completed_at=now - timedelta(seconds=90),
            duration_ms=10000,
        )
        task.execution_context = {
            "current_phase": "planning",
            "last_completed_step_id": planning_step.id,
            "execution_pointer": {
                "phase": "planning",
                "step_index": 1,
                "total_steps_in_phase": 1,
            },
            "progress": {
                "completed_steps": 1,
                "total_steps": 7,
                "progress": round(1 / 7, 2),
            },
        }
        task.trace = None  # 模拟 checkpoint 前崩溃
        await db_session.flush()

        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        refreshed = await _get_task(db_session, task.id)
        trace = refreshed.trace
        assert trace is not None
        # planning 阶段数据应从 research_steps 重建
        assert trace["phases"]["planning"] is not None
        assert trace["phases"]["planning"]["duration_ms"] == 10000
        # 所有阶段完成
        for phase in PHASE_ORDER:
            assert trace["phases"][phase] is not None


# ═══════════════════════════════════════════════════════════════
# 4. 数据一致性
# ═══════════════════════════════════════════════════════════════


class TestDataConsistency:
    """断点续跑后的数据一致性验证。"""

    @pytest.mark.asyncio
    async def test_evidence只追加不覆盖(self, db_session):
        """Synthesis 失败后 Retry，EvidenceItem 数量不减少。"""
        task = await _seed_failed_task(
            db_session,
            completed_through="rerank",
            failed_at="synthesis",
            recoverable=True,
            error_code="E3104",
        )

        # retry 前 Evidence 数量（rerank 阶段应已生成）
        evidence_before = await db_session.scalar(
            select(func.count()).select_from(EvidenceItem).where(EvidenceItem.task_id == task.id)
        )
        assert evidence_before == 4

        # 调用 retry_task 重置状态
        await retry_task(db_session, task)
        await db_session.flush()

        # Retry 并完整执行
        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        evidence_after_retry = await db_session.scalar(
            select(func.count()).select_from(EvidenceItem).where(EvidenceItem.task_id == task.id)
        )

        # Evidence 只追加不覆盖（rerank 重新执行会清空后写入，数量应保持 4）
        assert evidence_after_retry >= evidence_before

    @pytest.mark.asyncio
    async def test_completed_steps和progress恢复后正确(self, db_session):
        """崩溃恢复后 completed_steps 和 progress 不超出 [0,1] 范围。"""
        task = await _seed_crash_task(db_session, crash_after="fetch")

        with patch("app.tasks.research_task.async_session_factory", new=_session_factory(db_session)):
            with ExitStack() as stack:
                for p in _mock_pipeline_external(db_session, task.id):
                    stack.enter_context(p)
                async with _commit_to_flush(db_session):
                    result = await _run_pipeline(task.id)

        assert result["status"] == "completed"

        refreshed = await _get_task(db_session, task.id)
        assert refreshed.completed_steps == 7
        assert refreshed.total_steps == 7
        ec = refreshed.execution_context or {}
        progress = ec.get("progress", {})
        assert progress.get("completed_steps") == 7
        assert progress.get("total_steps") == 7
        assert progress.get("progress") == 1.0


# ═══════════════════════════════════════════════════════════════
# 5. Retry API 前置校验
# ═══════════════════════════════════════════════════════════════


class TestRetryApiValidation:
    """通过 FastAPI 测试客户端验证 Retry API 前置校验。"""

    @pytest.mark.asyncio
    async def test_running任务_retry_返回E2003(self, db_session, async_client, auth_headers):
        """running 状态任务调用 retry 返回 E2003。"""
        task = await _seed_task(db_session, status="running")
        from tests.integration._retry_helpers import _create_step
        await _create_step(db_session, task.id, "planning", status="running")

        with patch("app.api.research._execute_research_task.delay") as mock_delay:
            response = await async_client.post(
                f"/api/research/{task.id}/retry",
                headers=auth_headers,
            )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "E2003"
        assert "allowed_statuses" in body["detail"]
        mock_delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_recoverable为false的failed任务_retry_返回E2003(self, db_session, async_client, auth_headers):
        """recoverable=false 的 failed 任务调用 retry 返回 E2003。"""
        task = await _seed_task(
            db_session,
            status="failed",
            recoverable=False,
            error_code="E3101",
        )

        with patch("app.api.research._execute_research_task.delay") as mock_delay:
            response = await async_client.post(
                f"/api/research/{task.id}/retry",
                headers=auth_headers,
            )

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "E2003"
        mock_delay.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# 6. SSE 事件完整性
# ═══════════════════════════════════════════════════════════════


class TestSseEventIntegrity:
    """Retry 后 SSE 事件序列完整性验证。"""

    @pytest.mark.asyncio
    async def test_retry后SSE事件序列完整(self, db_session):
        """Retry 后应发送完整的 task.created → ... → checkpoint.saved → task.completed 序列。"""
        task = await _seed_failed_task(
            db_session,
            completed_through="rerank",
            failed_at="synthesis",
            recoverable=True,
            error_code="E3104",
        )

        await retry_task(db_session, task)
        await db_session.flush()

        sse_bridge = SSEBridge(task.id)
        published = _record_sse_events(sse_bridge)
        trace = TraceRecorder(task_id=task.id, user_id=1, topic=task.topic, previous_trace=task.trace)
        handlers = build_default_phase_handlers()

        patches = _mock_pipeline_external(db_session, task.id)
        async with _commit_to_flush(db_session):
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                orchestrator = PipelineOrchestrator(
                    task=task,
                    session=db_session,
                    sse_bridge=sse_bridge,
                    trace_recorder=trace,
                    phase_handlers=handlers,
                )
                await orchestrator.run()

        assert task.status == "completed"

        event_types = [e[0] for e in published]
        assert event_types[0] == EVENT_TASK_CREATED
        assert event_types[-1] == EVENT_TASK_COMPLETED

        # Retry 场景：planning~rerank 已 completed 被跳过，仅 synthesis/evidence_graph/render 实际执行
        executed_phases = ["synthesizing", "building_evidence_graph", "rendering"]
        for phase in executed_phases:
            started = [e for e in published if e[0] == EVENT_PHASE_STARTED and e[1].get("phase") == phase]
            completed = [e for e in published if e[0] == EVENT_PHASE_COMPLETED and e[1].get("phase") == phase]
            assert len(started) == 1, f"Phase {phase} 缺少 phase.started"
            assert len(completed) == 1, f"Phase {phase} 缺少 phase.completed"

        # checkpoint.saved 由实际执行的 Phase  emit（skip 的 completed Step 不 emit）
        assert event_types.count(EVENT_CHECKPOINT_SAVED) == 3

        # 最终 progress = 1.0
        progress_events = [e for e in published if e[0] == EVENT_TASK_PROGRESS]
        final_progress = progress_events[-1][1]
        assert final_progress["completed_steps"] == 7
        assert final_progress["total_steps"] == 7
        assert final_progress["progress"] == 1.0

    @pytest.mark.asyncio
    async def test_recoverable失败时_task_failed携带last_checkpoint(self, db_session):
        """recoverable=true 的失败 SSE 事件应携带 last_checkpoint。"""
        from app.core.exceptions import SynthesisFailedException

        task = await _seed_failed_task(
            db_session,
            completed_through="rerank",
            failed_at="synthesis",
            recoverable=True,
            error_code="E3104",
        )

        # 将任务重置为 pending，使 Orchestrator 能进入执行流并在 synthesis 失败时 emit task.failed
        task.status = "pending"
        await db_session.flush()

        sse_bridge = SSEBridge(task.id)
        published = _record_sse_events(sse_bridge)

        async def _failing_synthesis(*args, **kwargs):
            raise SynthesisFailedException(detail="模拟 Synthesis 失败")

        handlers = build_default_phase_handlers()
        handlers["synthesis"] = _failing_synthesis

        patches = _mock_pipeline_external(db_session, task.id)
        async with _commit_to_flush(db_session):
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                orchestrator = PipelineOrchestrator(
                    task=task,
                    session=db_session,
                    sse_bridge=sse_bridge,
                    trace_recorder=TraceRecorder(task_id=task.id, user_id=1, topic=task.topic),
                    phase_handlers=handlers,
                )
                await orchestrator.run()

        assert task.status == "failed"

        failed_events = [e for e in published if e[0] == EVENT_TASK_FAILED]
        assert len(failed_events) == 1
        payload = failed_events[0][1]
        assert payload["recoverable"] is True
        assert "last_checkpoint" in payload
        assert payload["last_checkpoint"] is not None
