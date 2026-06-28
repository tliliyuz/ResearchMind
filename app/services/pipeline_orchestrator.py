"""Pipeline Orchestrator —— 七阶段调度、状态转换、Execution Context 更新。

Phase 调度（Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render），
每个 Phase 创建 ResearchStep → 幂等锁检查 → 调用 Phase 函数 → 原子写入
Execution Context → SSE 事件推送 → TaskStateResolver 评估。

设计对齐 ARCHITECTURE.md §3.3 / RESEARCH_PIPELINE.md §1.2。

Phase 函数注册表：
- planning / search / fetch → Phase 2 stub（§3.3-§3.5 实现）
- rerank / synthesis → Phase 3 实现
- evidence_graph / render → 自动跳过（Phase 3 后续实现）
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select as sa_select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cost_tracker import extract_step_cost
from app.core.exceptions import extract_recoverable_from_exception
from app.core.task_state_resolver import FATAL_STEP_ERROR_CODES, TaskStateResolver
from app.core.trace_recorder import TraceRecorder
from app.models.enums import TASK_PHASE_ENUM, STEP_TYPE_ENUM
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.pipeline.evidence_graph import run_evidence_graph
from app.pipeline.fetcher import run_fetch
from app.pipeline.planner import run_planning
from app.pipeline.renderer import run_render
from app.pipeline.reranker import run_rerank
from app.pipeline.searcher import run_search
from app.pipeline.synthesizer import run_synthesis
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_CHECKPOINT_SAVED,
    EVENT_PHASE_COMPLETED,
    EVENT_PHASE_STARTED,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    EVENT_STEP_STARTED,
    EVENT_TASK_CANCELED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_CREATED,
    EVENT_TASK_FAILED,
    EVENT_TASK_PROGRESS,
    EVENT_TASK_WARNING,
)
from app.tasks.lock import acquire_step_lock_async, release_step_lock_async

logger = logging.getLogger(__name__)

# ── 工具函数 ────────────────────────────────────────────────


# ── Phase 函数类型 ──────────────────────────────────────────

PhaseFunc = Callable[
    [ResearchTask, ResearchStep, AsyncSession, SSEBridge],
    Any,  # 返回 output dict（协程）
]

# ── Phase 常量 ──────────────────────────────────────────────

# 七阶段 step_type 顺序（线性串行，v1.0）
PHASE_ORDER: list[str] = list(STEP_TYPE_ENUM)

# 阶段标签（前端展示用）
PHASE_LABELS: dict[str, str] = {
    "planning": "Planning：拆解研究主题",
    "search": "Search：多子问题搜索",
    "fetch": "Fetch：网页内容抓取",
    "rerank": "Rerank：来源粗筛精排",
    "synthesis": "Synthesis：跨源综合",
    "evidence_graph": "来源图谱：结构化认知资产构建",
    "render": "Render：报告渲染",
}

# Phase → phase 名称映射（step_type → TASK_PHASE_ENUM 的进行时名称）
STEP_TYPE_TO_PHASE: dict[str, str] = {
    "planning": "planning",
    "search": "searching",
    "fetch": "fetching",
    "rerank": "reranking",
    "synthesis": "synthesizing",
    "evidence_graph": "building_evidence_graph",
    "render": "rendering",
}

# 致命 Phase：这些阶段一旦发生非 AppException 的未知异常，不应降级继续，
# 必须终止 Pipeline，避免错误被延迟到后续阶段才暴露。
FATAL_STEP_TYPES: frozenset[str] = frozenset({
    "planning", "search", "rerank", "synthesis", "evidence_graph", "render"
})


# ═════════════════════════════════════════════════════════════
# Pipeline Orchestrator
# ═════════════════════════════════════════════════════════════


class PipelineOrchestrator:
    """Pipeline 编排器 —— 调度七阶段执行。

    每个 Phase 内：
    1. 创建 ResearchStep（pending）
    2. 幂等锁检查（防重复入队）
    3. 更新 step status → running
    4. 发送 phase.started / step.started SSE 事件
    5. 调用 Phase 函数
    6. 更新 step output + status → completed
    7. 原子更新 execution_context
    8. 发送 step.completed / phase.completed / task.progress SSE 事件
    9. 调用 TaskStateResolver 检查是否提前终止
    10. 释放幂等锁

    Usage:
        orchestrator = PipelineOrchestrator(
            task=task,
            session=session,
            sse_bridge=SSEBridge(task.id),
            trace_recorder=TraceRecorder(task_id=str(task.id), ...),
            phase_handlers={"planning": run_planning, ...},
        )
        await orchestrator.run()
    """

    def __init__(
        self,
        task: ResearchTask,
        session: AsyncSession,
        sse_bridge: SSEBridge,
        trace_recorder: TraceRecorder,
        phase_handlers: dict[str, PhaseFunc] | None = None,
    ):
        """初始化编排器。

        Args:
            task: ResearchTask ORM 实例（已加载到 session）
            session: 异步数据库会话
            sse_bridge: SSE 事件发布器实例
            trace_recorder: Trace 追踪器实例
            phase_handlers: Phase 函数注册表（step_type → async func），
                           未注册的 phase 自动跳过
        """
        self._task = task
        self._session = session
        self._sse = sse_bridge
        self._trace = trace_recorder
        self._handlers = phase_handlers or {}
        self._resolver = TaskStateResolver()
        self._last_step_id: str | None = None

    # ── 主入口 ──────────────────────────────────────────────

    async def run(self) -> None:
        """执行全 Pipeline（七阶段串行）。

        Raises:
            Exception: 致命错误（已更新 task status 为 failed）
        """
        task_id = str(self._task.id)
        logger.info("Pipeline 开始: task_id=%s", task_id)

        try:
            # 1. 任务状态 pending → running（CAS + commit）
            started = await self._start_task()
            if not started:
                logger.warning("任务未成功启动，停止 Pipeline: task_id=%s", task_id)
                return

            # 2. 依次执行 7 个 Phase
            for step_type in PHASE_ORDER:
                # 阶段重载：检查是否已取消
                await self._session.refresh(self._task, ["status"])
                if self._task.status == "canceled":
                    logger.info("任务已被取消，停止 Pipeline: task_id=%s", task_id)
                    if self._task.completed_at is None:
                        self._task.completed_at = datetime.now(timezone.utc)
                    await self._session.commit()
                    await self._sse.publish(EVENT_TASK_CANCELED, {
                        "task_id": task_id,
                        "status": "canceled",
                    })
                    return

                await self._run_phase(step_type)
                # 每 Phase 完成后持久化 checkpoint（S4）
                await self._session.commit()

            # 3. 全部 Phase 完成 → 推导最终状态
            await self._finalize_task()
            await self._session.commit()

        except Exception as e:
            logger.exception("Pipeline 致命错误: task_id=%s, error=%s", task_id, e)
            await self._handle_fatal_error(e)
            await self._session.commit()

    # ── 任务启动 ────────────────────────────────────────────

    async def _start_task(self) -> bool:
        """将任务从 pending 转为 running（CAS + commit），发送 task.created 事件。

        Returns:
            bool: CAS 成功返回 True，失败返回 False。
        """
        task_id = str(self._task.id)
        now = datetime.now(timezone.utc)

        # CAS: 仅当 status='pending' 时才更新为 running
        result = await self._session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.status == "pending")
            .values(status="running", started_at=now)
        )
        if result.rowcount == 0:
            # CAS 失败时显式查询当前状态，避免访问可能过期的 self._task
            current_status = None
            try:
                status_result = await self._session.execute(
                    sa_select(ResearchTask.status).where(ResearchTask.id == task_id)
                )
                current_status = status_result.scalar_one_or_none()
            except Exception:
                logger.exception("查询任务状态时异常: task_id=%s", task_id)
            logger.warning(
                "CAS 失败：任务状态已变更，跳过启动: task_id=%s, current_status=%s",
                task_id, current_status,
            )
            return False
        await self._session.commit()

        # 刷新 ORM 对象让内存状态与 DB 一致
        await self._session.refresh(self._task)

        # 安全保障：修正旧任务（AB 修复前创建）的 total_steps 为固定七阶段
        # 避免 _update_total_steps_on_completion 遗留的动态值导致 6/27=22% 问题
        old_total = self._task.total_steps
        if old_total != len(PHASE_ORDER):
            self._task.total_steps = len(PHASE_ORDER)
            await self._session.commit()
            logger.info(
                "修正 total_steps: task_id=%s, old=%s → new=%d",
                task_id, old_total, len(PHASE_ORDER),
            )

        await self._sse.publish(EVENT_TASK_CREATED, {
            "task_id": str(self._task.id),
            "status": "running",
            "created_at": self._task.created_at.isoformat() if self._task.created_at else None,
        })

        logger.info("任务启动: task_id=%s", self._task.id)
        return True

    # ── 单 Phase 执行 ───────────────────────────────────────

    async def _run_phase(self, step_type: str) -> None:
        """执行单个 Phase（创建 Step → 幂等锁 → 执行 → 更新 Context）。

        Args:
            step_type: Phase 类型（planning / search / ... / render）
        """
        phase_name = STEP_TYPE_TO_PHASE.get(step_type, step_type)
        task_id = str(self._task.id)  # 提前缓存，避免异常后 session 中毒时触发懒加载

        # 1. 创建 Step
        step = await self._create_step(step_type)
        step_id = str(step.id)
        self._last_step_id = step_id

        # 1.5 Step 终态检查（防御深度：Phase4 断点续跑后，可能遇到已完成的 Step）
        TERMINAL_STATUSES = {"completed", "failed", "skipped"}
        if step.status in TERMINAL_STATUSES:
            logger.info(
                "Step 已处于终态，跳过执行: step_id=%s, type=%s, status=%s",
                step_id, step_type, step.status,
            )
            return

        # 2. 幂等锁检查
        locked = await acquire_step_lock_async(
            task_id, step_type,
            ttl=settings.CELERY_IDEMPOTENCY_LOCK_TTL,
        )
        if not locked:
            logger.warning(
                "Step 幂等锁已被占用，跳过: task_id=%s, step_type=%s",
                task_id, step_type,
            )
            step.status = "skipped"
            step.output = {"reason": "幂等锁已被占用（可能重复入队）"}
            await self._session.flush()
            return

        try:
            # 3. 检查 handler 是否存在
            handler = self._handlers.get(step_type)
            if handler is None:
                await self._skip_phase(step, phase_name, reason=f"Phase 函数未注册（等待 Phase 3 实现）")
                return

            # 4. 更新 Step + Phase 状态 → running
            await self._start_step(step, phase_name)

            # 5. 执行 Phase 函数
            output = await handler(self._task, step, self._session, self._sse)
            # output 可以是 dict 或 None；若是协程返回的 awaitable，handler 内部已 await

            # 6. Step 完成
            await self._complete_step(step, phase_name, output)

        except Exception as e:
            await self._handle_step_error(step, phase_name, e)
        finally:
            # 7. 释放幂等锁
            await release_step_lock_async(task_id, step_type)

    # ── 工具方法 ──────────────────────────────────────────────

    def _get_last_checkpoint(self, execution_context: dict | None) -> str | None:
        """从 execution_context 中安全读取 last_completed_step_id。"""
        context = execution_context or {}
        if isinstance(context, dict):
            last = context.get("last_completed_step_id")
            if last:
                return str(last)
        return None

    def _build_task_failed_payload(
        self,
        task_id: str,
        error_type: str,
        error_description: str,
        recoverable: bool,
        execution_context: dict | None = None,
    ) -> dict:
        """构造 task.failed SSE payload。

        仅 recoverable=true 时附带 last_checkpoint，供客户端断点续跑。
        """
        payload: dict = {
            "task_id": task_id,
            "error_type": error_type,
            "error_description": error_description,
            "recoverable": recoverable,
        }
        if recoverable:
            last_checkpoint = self._get_last_checkpoint(execution_context)
            if last_checkpoint:
                payload["last_checkpoint"] = last_checkpoint
        return payload

    # ── Step 生命周期 ───────────────────────────────────────

    async def _create_step(self, step_type: str) -> ResearchStep:
        """创建或复用 ResearchStep（仅匹配主 Step，parent_step_id IS NULL）。

        复用优先级（三层）：
        1. 断点续跑：复用已成功完成的 Step（completed / skipped），
           交由 _run_phase() 的终端检查跳过执行；
        2. 崩溃恢复：复用 pending / running 的遗留 Step，继续执行；
        3. 全新创建：以上均不命中则新建 Step（pending 状态）。

        所有查询均过滤 parent_step_id IS NULL，确保不会误匹配
        search/fetch 阶段内部创建的子 Step。
        """
        # 1. 断点续跑：复用已完成 Step（仅主 Step）
        result = await self._session.execute(
            sa_select(ResearchStep)
            .where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type == step_type,
                ResearchStep.status.in_(["completed", "skipped"]),
                ResearchStep.parent_step_id == None,
            )
            .order_by(ResearchStep.completed_at.desc())
            .limit(1)
        )
        existing_terminal = result.scalar_one_or_none()
        if existing_terminal is not None:
            logger.debug(
                "Step 复用（已完成）: step_id=%s, type=%s, status=%s",
                existing_terminal.id, step_type, existing_terminal.status,
            )
            return existing_terminal

        # 2. 崩溃恢复：复用已有非终态 Step（仅主 Step，按 started_at 升序，pending 的 NULL 在最前）
        result = await self._session.execute(
            sa_select(ResearchStep)
            .where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type == step_type,
                ResearchStep.status.in_(["pending", "running"]),
                ResearchStep.parent_step_id == None,
            )
            .order_by(ResearchStep.started_at)
            .limit(1)
        )
        existing_step = result.scalar_one_or_none()
        if existing_step is not None:
            logger.debug(
                "Step 复用（待执行）: step_id=%s, type=%s, status=%s",
                existing_step.id, step_type, existing_step.status,
            )
            return existing_step

        # 3. 全新创建（主 Step，parent_step_id 通过 _last_step_id 维护链式关系）
        step = ResearchStep(
            task_id=self._task.id,
            step_type=step_type,
            parent_step_id=self._last_step_id,
            status="pending",
            label=PHASE_LABELS.get(step_type, step_type),
        )
        self._session.add(step)
        await self._session.flush()

        # 注意：task.total_steps 在创建任务时已初始化为七阶段总数，
        # 子 step 不应影响全局进度分母，因此此处不再递增。

        logger.debug("Step 创建: step_id=%s, type=%s", step.id, step_type)
        return step

    async def _start_step(self, step: ResearchStep, phase_name: str) -> None:
        """更新 Step + Task phase → running，发送 SSE 事件。"""
        now = datetime.now(timezone.utc)

        # Step → running
        step.status = "running"
        step.started_at = now
        await self._session.flush()

        # Task phase 更新（第一阶段或阶段变更时发送 phase.started）
        previous_phase = self._task.current_phase
        self._task.current_phase = phase_name
        await self._session.flush()

        if previous_phase != phase_name:
            await self._sse.publish(EVENT_PHASE_STARTED, {
                "phase": phase_name,
                "timestamp": now.isoformat(),
            })

        await self._sse.publish(EVENT_STEP_STARTED, {
            "step_id": str(step.id),
            "step_type": step.step_type,
            "label": step.label,
            "timestamp": now.isoformat(),
        })

    async def _complete_step(
        self,
        step: ResearchStep,
        phase_name: str,
        output: Any,
    ) -> None:
        """Step 正常完成：更新状态 + Execution Context + SSE 事件。"""
        now = datetime.now(timezone.utc)

        # 计算耗时
        duration_ms = None
        if step.started_at:
            delta = now - step.started_at
            duration_ms = int(delta.total_seconds() * 1000)

        # Step → completed
        step.status = "completed"
        step.completed_at = now
        step.duration_ms = duration_ms
        step.output = output if isinstance(output, dict) else {"result": str(output)}
        step.cost = extract_step_cost(step.output, default_model=settings.LLM_MODEL)
        await self._session.flush()

        # 更新 task 统计
        self._task.completed_steps = (self._task.completed_steps or 0) + 1

        # 原子更新 Execution Context
        await self._update_execution_context(step, phase_name)

        # SSE 事件
        await self._sse.publish(EVENT_STEP_COMPLETED, {
            "step_id": str(step.id),
            "output": step.output,
        })

        await self._sse.publish(EVENT_PHASE_COMPLETED, {
            "phase": phase_name,
            "duration_ms": duration_ms,
        })

        # 全局进度
        total = self._task.total_steps or 1
        completed = self._task.completed_steps or 0
        progress = round(completed / total, 2) if total > 0 else 0.0
        await self._sse.publish(EVENT_TASK_PROGRESS, {
            "completed_steps": completed,
            "total_steps": total,
            "progress": progress,
        })

        # Checkpoint
        await self._sse.publish(EVENT_CHECKPOINT_SAVED, {
            "phase": phase_name,
            "last_completed_step_id": str(step.id),
            "saved_at": now.isoformat(),
        })

        # Trace 埋点（Planning / Search / Fetch / Rerank / Synthesis / Evidence Graph / Render）
        if isinstance(output, dict):
            step_type = step.step_type
            if step_type == "planning":
                self._trace.record_planning(
                    duration_ms=duration_ms or 0,
                    input_tokens=output.get("prompt_tokens", 0),
                    output_tokens=output.get("completion_tokens", 0),
                    sub_questions_count=len(output.get("sub_questions", [])),
                    retries=output.get("retry_count", 0),
                    model=output.get("model"),
                )
            elif step_type == "search":
                sub_results = output.get("sub_question_results", [])
                total_results = output.get("total_results", 0)
                success_count = sum(1 for sr in sub_results if sr.get("status") == "completed")
                skipped_count = sum(1 for sr in sub_results if sr.get("status") == "skipped")
                self._trace.record_search(
                    duration_ms=duration_ms or 0,
                    total_results=total_results,
                    success_count=success_count,
                    skipped_count=skipped_count,
                    failed_count=0,
                    cost_usd=output.get("search_cost_usd", 0.0),
                )
            elif step_type == "fetch":
                fetched = output.get("fetched", [])
                total_content_bytes = sum(
                    item.get("content_length", 0) for item in fetched
                    if isinstance(item.get("content_length"), int)
                )
                self._trace.record_fetch(
                    duration_ms=duration_ms or 0,
                    total_urls=len(fetched),
                    success_count=output.get("successful", 0),
                    skipped_count=output.get("skipped_safety", 0),
                    failed_count=output.get("failed", 0),
                    total_content_bytes=total_content_bytes,
                    cost_usd=output.get("fetch_cost_usd", 0.0),
                )
            elif step_type == "rerank":
                self._trace.record_rerank(
                    duration_ms=duration_ms or 0,
                    bm25_candidates=output.get("bm25_candidates", 0),
                    llm_reranked=output.get("evidence_count", 0),
                    input_tokens=output.get("prompt_tokens", 0),
                    output_tokens=output.get("completion_tokens", 0),
                    retries=output.get("retry_count", 0),
                    model=output.get("model"),
                )
            elif step_type == "synthesis":
                self._trace.record_synthesis(
                    duration_ms=duration_ms or 0,
                    input_tokens=output.get("prompt_tokens", 0),
                    output_tokens=output.get("completion_tokens", 0),
                    clusters_count=output.get("clusters_count", 0),
                    conflicts_count=output.get("conflicts_count", 0),
                    knowledge_gaps_count=output.get("gaps_count", 0),
                    retries=output.get("retry_count", 0),
                    model=output.get("model"),
                )
            elif step_type == "evidence_graph":
                self._trace.record_evidence_graph(
                    duration_ms=duration_ms or 0,
                    evidence_count=output.get("item_count", 0),
                    source_count=output.get("source_count", 0),
                )
            elif step_type == "render":
                self._trace.record_render(
                    duration_ms=duration_ms or 0,
                    input_tokens=output.get("prompt_tokens", 0),
                    output_tokens=output.get("completion_tokens", 0),
                    sections_count=output.get("sections_count", 0),
                    citations_count=output.get("citations_count", 0),
                    retries=output.get("retry_count", 0),
                    model=output.get("model"),
                )

        # 检查是否需要提前终止（当前阶段 fatal 等）
        await self._check_early_termination()

        logger.info(
            "Step 完成: step_id=%s, type=%s, duration_ms=%s",
            step.id, step.step_type, duration_ms,
        )

    async def _skip_phase(
        self,
        step: ResearchStep,
        phase_name: str,
        reason: str,
    ) -> None:
        """跳过 Phase（handler 未注册或无条件跳过）。"""
        now = datetime.now(timezone.utc)

        step.status = "skipped"
        step.started_at = now
        step.completed_at = now
        step.output = {"reason": reason}
        await self._session.flush()

        self._task.completed_steps = (self._task.completed_steps or 0) + 1
        await self._update_execution_context(step, phase_name)

        await self._sse.publish(EVENT_STEP_STARTED, {
            "step_id": str(step.id),
            "step_type": step.step_type,
            "label": step.label,
            "timestamp": now.isoformat(),
        })
        await self._sse.publish(EVENT_STEP_SKIPPED, {
            "step_id": str(step.id),
            "reason": reason,
        })
        await self._sse.publish(EVENT_PHASE_COMPLETED, {
            "phase": phase_name,
            "duration_ms": 0,
        })
        await self._sse.publish(EVENT_CHECKPOINT_SAVED, {
            "phase": phase_name,
            "last_completed_step_id": str(step.id),
            "saved_at": now.isoformat(),
        })

        logger.info("Phase 跳过: step_type=%s, reason=%s", step.step_type, reason)

    async def _handle_step_error(
        self,
        step: ResearchStep,
        phase_name: str,
        error: Exception,
    ) -> None:
        """处理 Step 执行错误。"""
        now = datetime.now(timezone.utc)
        error_msg = str(error)

        # 获取错误码（如果异常是 AppException 子类）
        error_code = getattr(error, "error_code", None)

        step.status = "failed"
        step.completed_at = now
        step.error_code = error_code
        step.error_message = error_msg
        if step.started_at:
            delta = now - step.started_at
            step.duration_ms = int(delta.total_seconds() * 1000)
        await self._session.flush()

        await self._sse.publish(EVENT_STEP_FAILED, {
            "step_id": str(step.id),
            "error_type": error.__class__.__name__,
        })

        # 判断是否致命
        is_known_fatal = error_code and error_code in FATAL_STEP_ERROR_CODES
        is_unknown_fatal = (not error_code) and step.step_type in FATAL_STEP_TYPES

        if is_known_fatal or is_unknown_fatal:
            # 未知异常在致命 Phase 中 → 使用通用致命错误码
            if is_unknown_fatal:
                error_code = "E3999"
                step.error_code = error_code

            # flush 前读取 task 属性，避免 flush 后对象过期触发 lazy load
            task_id = str(self._task.id)
            execution_context = getattr(self._task, "execution_context", None)

            recoverable = extract_recoverable_from_exception(error) if is_known_fatal else False
            # 不在此处发送 task.failed——重新抛出后由 run() → _handle_fatal_error
            # 统一处理，避免 SSE double-emit。
            raise  # 重新抛出，由 run() 的顶层 try/except 处理

        # 可降级失败 → warning
        await self._sse.publish(EVENT_TASK_WARNING, {
            "step_id": str(step.id),
            "error_description": error_msg,
        })

        logger.warning(
            "Step 失败（可降级）: step_id=%s, type=%s, error=%s",
            step.id, step.step_type, error_msg,
        )

    # ── Execution Context ────────────────────────────────────

    async def _update_execution_context(
        self,
        step: ResearchStep,
        phase_name: str,
    ) -> None:
        """原子更新 execution_context（与 Step 状态在同一事务内）。

        更新内容：
        - current_phase: 当前 Phase 名称
        - last_completed_step_id: 最后完成的 Step UUID
        - execution_pointer: Phase 内进度（step_index / total_steps_in_phase）
        - progress: 全局进度快照（completed_steps / total_steps / progress）
        """
        total = self._task.total_steps or 1
        completed = self._task.completed_steps or 0
        progress = round(completed / total, 2) if total > 0 else 0.0

        # 统计当前 Phase 内的 Step 数量（通过 step_type 列，即 phase 标识）
        count_result = await self._session.execute(
            sa_select(func.count()).select_from(ResearchStep).where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type == step.step_type,
            )
        )
        phase_total = count_result.scalar() or 1
        # 统计已完成数量
        completed_result = await self._session.execute(
            sa_select(func.count()).select_from(ResearchStep).where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type == step.step_type,
                ResearchStep.status.in_(["completed", "skipped"]),
            )
        )
        phase_completed = completed_result.scalar() or 0

        context = {
            "current_phase": phase_name,
            "last_completed_step_id": str(step.id),
            "execution_pointer": {
                "phase": phase_name,
                "step_index": phase_completed,
                "total_steps_in_phase": phase_total,
            },
            "progress": {
                "completed_steps": completed,
                "total_steps": total,
                "progress": progress,
            },
        }

        self._task.execution_context = context
        await self._session.flush()

    # ── Step 加载 ───────────────────────────────────────────

    async def _load_task_steps(self) -> list[ResearchStep]:
        """重新加载当前任务的全部 Step。

        由于 async_session_factory 设置 expire_on_commit=False，且 task 通过
        session.get() 加载时 steps 关系不会自动预取，session.refresh(task, ["steps"])
        在异步会话中对集合关系的刷新不可靠（可能返回空或旧快照）。Resolver 需要
        基于最新 Step 状态推导 Task 状态，因此显式查询 research_steps 表，并强制
        使用 populate_existing 覆盖 identity map 中可能过期的 Step 对象。
        """
        try:
            result = await self._session.execute(
                sa_select(ResearchStep)
                .where(ResearchStep.task_id == self._task.id)
                .order_by(ResearchStep.started_at)
                .execution_options(populate_existing=True)
            )
            steps = list(result.scalars().all())
            if steps:
                logger.debug(
                    "_load_task_steps 加载 Step: task_id=%s, count=%d, statuses=%s",
                    self._task.id,
                    len(steps),
                    [s.status for s in steps],
                )
                return steps
        except Exception as exc:
            logger.debug(
                "显式查询 Step 失败，回退到 task.steps: task_id=%s, error=%s",
                self._task.id, exc,
            )

        # 兜底：显式查询未返回 Step 时（测试 mock 或查询为空），回退到 task.steps
        await self._session.refresh(self._task, ["steps"])
        return list(self._task.steps) if hasattr(self._task, "steps") else []

    # ── 提前终止检查 ────────────────────────────────────────

    async def _check_early_termination(self) -> None:
        """每 Step 完成后调用 TaskStateResolver 检查是否需要提前终止。

        如果 Resolver 返回 failed 且不可恢复，则提前终止 Pipeline。
        """
        steps = await self._load_task_steps()

        # 获取当前 evidence 数量
        evidence_count = self._task.total_evidence or 0

        new_status, error_info = self._resolver.resolve(
            self._task, steps, evidence_count,
        )

        if new_status == "failed" and error_info:
            # 致命失败 → 提前终止（CAS）
            now = datetime.now(timezone.utc)
            # flush 前读取 task 属性，避免 flush 后对象过期触发 lazy load
            task_id = str(self._task.id)
            execution_context = getattr(self._task, "execution_context", None)

            result = await self._session.execute(
                sa_update(ResearchTask)
                .where(ResearchTask.id == task_id, ResearchTask.status == "running")
                .values(
                    status="failed",
                    error_code=error_info.get("error_code"),
                    error_message=error_info.get("error_message"),
                    recoverable=error_info.get("recoverable", False),
                    completed_at=now,
                )
            )
            await self._session.flush()

            if result.rowcount == 0:
                await self._session.refresh(self._task, ["status"])
                logger.warning(
                    "CAS 失败：提前终止时任务状态已变更: task_id=%s, current_status=%s",
                    task_id, self._task.status,
                )
                return

            payload = self._build_task_failed_payload(
                task_id=task_id,
                error_type=error_info.get("error_code", "Unknown"),
                error_description=error_info.get("error_message", ""),
                recoverable=error_info.get("recoverable", False),
                execution_context=execution_context,
            )
            await self._sse.publish(EVENT_TASK_FAILED, payload)

            raise TaskFatalException(
                f"Task 提前终止: {error_info.get('error_code')} - {error_info.get('error_message')}",
            )

    # ── 最终化 ──────────────────────────────────────────────

    async def _finalize_task(self) -> None:
        """全部 Phase 完成后推导最终 Task State 并写入（CAS）。"""
        steps = await self._load_task_steps()
        evidence_count = self._task.total_evidence or 0

        new_status, error_info = self._resolver.resolve(
            self._task, steps, evidence_count,
        )

        now = datetime.now(timezone.utc)
        trace_data = self._trace.finish()

        # CAS: 仅当 status='running' 时才写入最终状态
        values = {
            "status": new_status,
            "completed_at": now,
            "trace": trace_data,
        }
        if error_info:
            values["error_code"] = error_info.get("error_code")
            values["error_message"] = error_info.get("error_message")
            values["recoverable"] = error_info.get("recoverable", False)

        # flush 前读取 task 属性，避免 flush 后对象过期触发 lazy load
        task_id = str(self._task.id)
        task_started_at = self._task.started_at
        task_total_sources = self._task.total_sources
        task_total_evidence = self._task.total_evidence
        task_trace = self._task.trace
        execution_context = getattr(self._task, "execution_context", None)

        result = await self._session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.status == "running")
            .values(**values)
        )
        await self._session.flush()

        if result.rowcount == 0:
            await self._session.refresh(self._task, ["status"])
            logger.warning(
                "CAS 失败：最终化时任务状态已非 running: task_id=%s, current_status=%s",
                task_id, self._task.status,
            )
            if self._task.status == "running":
                raise RuntimeError(
                    f"CAS 更新失败但任务仍为 running: task_id={task_id}"
                )
            return

        # SSE 最终事件
        if new_status == "completed":
            await self._sse.publish(EVENT_TASK_COMPLETED, {
                "task_id": task_id,
                "status": "completed",
                "trace": {
                    "total_duration_ms": (
                        int((now - task_started_at).total_seconds() * 1000)
                        if task_started_at else 0
                    ),
                    "sources": task_total_sources or 0,
                    "evidence": task_total_evidence or 0,
                },
            })
        elif new_status == "partially_completed":
            await self._sse.publish(EVENT_TASK_COMPLETED, {
                "task_id": task_id,
                "status": "partially_completed",
                "trace": task_trace,
            })
        elif new_status == "failed":
            payload = self._build_task_failed_payload(
                task_id=task_id,
                error_type=error_info.get("error_code", "Unknown") if error_info else "Unknown",
                error_description=error_info.get("error_message", "") if error_info else "",
                recoverable=error_info.get("recoverable", False) if error_info else False,
                execution_context=execution_context,
            )
            await self._sse.publish(EVENT_TASK_FAILED, payload)

        logger.info(
            "Pipeline 完成: task_id=%s, status=%s, steps=%d, evidence=%d",
            task_id, new_status, len(steps), evidence_count,
        )

    async def _handle_fatal_error(self, error: Exception) -> None:
        """处理未捕获的致命错误：CAS 更新 task status 为 failed。"""
        # 先捕获 task 属性，避免 session 失效/对象过期后访问 self._task 触发懒加载。
        # Celery Worker 运行在同步 greenlet 中，懒加载会导致 MissingGreenlet。
        task_id = str(self._task.id)
        execution_context = getattr(self._task, "execution_context", None)

        # 若 session 已失效/rollback-only（如 DataError），先回滚使其恢复可用。
        # 注意：仅当 session 不活跃时才回滚，避免撤销已 flush 的 Step 失败状态。
        if not self._session.is_active:
            try:
                await self._session.rollback()
            except Exception:
                logger.exception("Session rollback 失败: task_id=%s", task_id)

        now = datetime.now(timezone.utc)
        error_code = getattr(error, "error_code", None) or "E3999"
        error_msg = str(error)
        recoverable = extract_recoverable_from_exception(error)

        # trace  finish 失败不应阻断状态写入
        try:
            trace_data = self._trace.finish()
        except Exception:
            logger.exception("Trace finish 失败: task_id=%s", task_id)
            trace_data = None

        # CAS: 仅当 status='running' 时才更新为 failed
        updated = False
        try:
            result = await self._session.execute(
                sa_update(ResearchTask)
                .where(ResearchTask.id == task_id, ResearchTask.status == "running")
                .values(
                    status="failed",
                    completed_at=now,
                    error_code=error_code,
                    error_message=error_msg,
                    recoverable=recoverable,
                    trace=trace_data,
                )
            )
            await self._session.flush()
            updated = result.rowcount > 0
        except Exception:
            logger.exception("写入失败状态时异常: task_id=%s", task_id)
            raise

        if not updated:
            # CAS 失败时显式查询当前状态，不访问可能已过期的 self._task
            current_status = None
            try:
                status_result = await self._session.execute(
                    sa_select(ResearchTask.status).where(ResearchTask.id == task_id)
                )
                current_status = status_result.scalar_one_or_none()
            except Exception:
                logger.exception("查询任务状态时异常: task_id=%s", task_id)
            logger.warning(
                "CAS 失败：致命错误处理时任务状态已非 running: task_id=%s, current_status=%s",
                task_id, current_status,
            )
            return

        # SSE 发送失败不应阻断状态更新
        try:
            payload = self._build_task_failed_payload(
                task_id=task_id,
                error_type=error.__class__.__name__,
                error_description=error_msg,
                recoverable=recoverable,
                execution_context=execution_context,
            )
            await self._sse.publish(EVENT_TASK_FAILED, payload)
        except Exception:
            logger.exception("SSE 发送失败: task_id=%s", task_id)


# ═════════════════════════════════════════════════════════════
# 异常
# ═════════════════════════════════════════════════════════════


class TaskFatalException(Exception):
    """任务致命错误（不可恢复），用于提前终止 Pipeline。"""
    pass


# ═════════════════════════════════════════════════════════════
# Phase 函数注册表构建
# ═════════════════════════════════════════════════════════════


def build_default_phase_handlers() -> dict[str, PhaseFunc]:
    """构建默认 Phase Handler 注册表。

    Phase 2（§3.3-§3.5）实现的阶段：planning / search / fetch
    Phase 3 实现的阶段：rerank / synthesis / evidence_graph / render
    """
    return {
        "planning": run_planning,
        "search": run_search,
        "fetch": run_fetch,
        "rerank": run_rerank,
        "synthesis": run_synthesis,
        "evidence_graph": run_evidence_graph,
        "render": run_render,
    }
