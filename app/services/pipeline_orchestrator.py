"""Pipeline Orchestrator —— 七阶段调度、状态转换、Execution Context 更新。

Phase 调度（Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render），
每个 Phase 创建 ResearchStep → 幂等锁检查 → 调用 Phase 函数 → 原子写入
Execution Context → SSE 事件推送 → TaskStateResolver 评估。

设计对齐 ARCHITECTURE.md §3.3 / RESEARCH_PIPELINE.md §1.2。

Phase 函数注册表：
- planning / search / fetch → Phase 2 stub（§3.3-§3.5 实现）
- rerank / synthesis / evidence_graph / render → 自动跳过（Phase 3 实现）
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func, select as sa_select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.task_state_resolver import FATAL_STEP_ERROR_CODES, TaskStateResolver
from app.core.trace_recorder import TraceRecorder
from app.models.enums import TASK_PHASE_ENUM, STEP_TYPE_ENUM
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_CHECKPOINT_SAVED,
    EVENT_PHASE_COMPLETED,
    EVENT_PHASE_STARTED,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    EVENT_STEP_STARTED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_CREATED,
    EVENT_TASK_FAILED,
    EVENT_TASK_PROGRESS,
    EVENT_TASK_WARNING,
)
from app.tasks.lock import acquire_step_lock_async, release_step_lock_async

logger = logging.getLogger(__name__)

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
    "rerank": "Rerank：证据粗筛精排",
    "synthesis": "Synthesis：跨源综合",
    "evidence_graph": "Evidence Graph：结构化认知资产构建",
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
            await self._start_task()

            # 2. 依次执行 7 个 Phase
            for step_type in PHASE_ORDER:
                # 阶段重载：检查是否已取消
                await self._session.refresh(self._task, ["status"])
                if self._task.status == "canceling":
                    logger.info("任务已被取消，停止 Pipeline: task_id=%s", task_id)
                    self._task.status = "canceled"
                    self._task.completed_at = datetime.now(timezone.utc)
                    await self._session.commit()
                    self._sse.publish(EVENT_TASK_FAILED, {
                        "task_id": task_id,
                        "error_type": "TaskCanceled",
                        "error_description": "任务已被用户取消",
                        "recoverable": False,
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

    async def _start_task(self) -> None:
        """将任务从 pending 转为 running（CAS + commit），发送 task.created 事件。"""
        now = datetime.now(timezone.utc)

        # CAS: 仅当 status='pending' 时才更新为 running
        result = await self._session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == self._task.id, ResearchTask.status == "pending")
            .values(status="running", started_at=now)
        )
        if result.rowcount == 0:
            logger.warning(
                "CAS 失败：任务状态已变更，跳过启动: task_id=%s, current_status=%s",
                self._task.id, self._task.status,
            )
            return
        await self._session.commit()

        # 刷新 ORM 对象让内存状态与 DB 一致
        await self._session.refresh(self._task)

        self._sse.publish(EVENT_TASK_CREATED, {
            "task_id": str(self._task.id),
            "status": "running",
            "created_at": self._task.created_at.isoformat() if self._task.created_at else None,
        })

        logger.info("任务启动: task_id=%s", self._task.id)

    # ── 单 Phase 执行 ───────────────────────────────────────

    async def _run_phase(self, step_type: str) -> None:
        """执行单个 Phase（创建 Step → 幂等锁 → 执行 → 更新 Context）。

        Args:
            step_type: Phase 类型（planning / search / ... / render）
        """
        phase_name = STEP_TYPE_TO_PHASE.get(step_type, step_type)

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
            str(self._task.id), step_type,
            ttl=settings.CELERY_IDEMPOTENCY_LOCK_TTL,
        )
        if not locked:
            logger.warning(
                "Step 幂等锁已被占用，跳过: task_id=%s, step_type=%s",
                self._task.id, step_type,
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
            await release_step_lock_async(str(self._task.id), step_type)

    # ── Step 生命周期 ───────────────────────────────────────

    async def _create_step(self, step_type: str) -> ResearchStep:
        """创建 ResearchStep（pending 状态）。"""
        now = datetime.now(timezone.utc)
        step = ResearchStep(
            task_id=self._task.id,
            step_type=step_type,
            parent_step_id=self._last_step_id,
            status="pending",
            label=PHASE_LABELS.get(step_type, step_type),
        )
        self._session.add(step)
        await self._session.flush()

        # 更新 task 计数
        self._task.total_steps = (self._task.total_steps or 0) + 1
        await self._session.flush()

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
            self._sse.publish(EVENT_PHASE_STARTED, {
                "phase": phase_name,
                "timestamp": now.isoformat(),
            })

        self._sse.publish(EVENT_STEP_STARTED, {
            "step_id": str(step.id),
            "step_type": step.step_type,
            "label": step.label,
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
        await self._session.flush()

        # 更新 task 统计
        self._task.completed_steps = (self._task.completed_steps or 0) + 1

        # 原子更新 Execution Context
        await self._update_execution_context(step, phase_name)

        # SSE 事件
        self._sse.publish(EVENT_STEP_COMPLETED, {
            "step_id": str(step.id),
            "output": step.output,
        })

        self._sse.publish(EVENT_PHASE_COMPLETED, {
            "phase": phase_name,
            "duration_ms": duration_ms,
        })

        # 全局进度
        total = self._task.total_steps or 1
        completed = self._task.completed_steps or 0
        progress = round(completed / total, 2) if total > 0 else 0.0
        self._sse.publish(EVENT_TASK_PROGRESS, {
            "completed_steps": completed,
            "total_steps": total,
            "progress": progress,
        })

        # Checkpoint
        self._sse.publish(EVENT_CHECKPOINT_SAVED, {
            "phase": phase_name,
            "last_completed_step_id": str(step.id),
            "saved_at": now.isoformat(),
        })

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

        self._sse.publish(EVENT_STEP_STARTED, {
            "step_id": str(step.id),
            "step_type": step.step_type,
            "label": step.label,
        })
        self._sse.publish(EVENT_STEP_SKIPPED, {
            "step_id": str(step.id),
            "reason": reason,
        })
        self._sse.publish(EVENT_PHASE_COMPLETED, {
            "phase": phase_name,
            "duration_ms": 0,
        })
        self._sse.publish(EVENT_CHECKPOINT_SAVED, {
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

        self._sse.publish(EVENT_STEP_FAILED, {
            "step_id": str(step.id),
            "error_type": error.__class__.__name__,
        })

        # 判断是否致命：检查 error_code 是否在 FATAL 集合中
        if error_code and error_code in FATAL_STEP_ERROR_CODES:
            self._sse.publish(EVENT_TASK_FAILED, {
                "task_id": str(self._task.id),
                "error_type": error.__class__.__name__,
                "error_description": error_msg,
                "recoverable": False,
            })
            raise  # 重新抛出，由 run() 的顶层 try/except 处理

        # 可降级失败 → warning
        self._sse.publish(EVENT_TASK_WARNING, {
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

    # ── 提前终止检查 ────────────────────────────────────────

    async def _check_early_termination(self) -> None:
        """每 Step 完成后调用 TaskStateResolver 检查是否需要提前终止。

        如果 Resolver 返回 failed 且不可恢复，则提前终止 Pipeline。
        """
        # 获取当前所有 steps（从 task.steps 关系）
        # 注意：task.steps 是 lazy="selectin"，已在加载 task 时预取
        steps = self._task.steps if hasattr(self._task, "steps") else []

        # 获取当前 evidence 数量
        evidence_count = self._task.total_evidence or 0

        new_status, error_info = self._resolver.resolve(
            self._task, steps, evidence_count,
        )

        if new_status == "failed" and error_info:
            # 致命失败 → 提前终止（CAS）
            now = datetime.now(timezone.utc)
            await self._session.execute(
                sa_update(ResearchTask)
                .where(ResearchTask.id == self._task.id, ResearchTask.status == "running")
                .values(
                    status="failed",
                    error_code=error_info.get("error_code"),
                    error_message=error_info.get("error_message"),
                    recoverable=error_info.get("recoverable", False),
                    completed_at=now,
                )
            )
            await self._session.flush()

            self._sse.publish(EVENT_TASK_FAILED, {
                "task_id": str(self._task.id),
                "error_type": error_info.get("error_code", "Unknown"),
                "error_description": error_info.get("error_message", ""),
                "recoverable": error_info.get("recoverable", False),
            })

            raise TaskFatalException(
                f"Task 提前终止: {error_info.get('error_code')} - {error_info.get('error_message')}",
            )

    # ── 最终化 ──────────────────────────────────────────────

    async def _finalize_task(self) -> None:
        """全部 Phase 完成后推导最终 Task State 并写入（CAS）。"""
        steps = self._task.steps if hasattr(self._task, "steps") else []
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

        result = await self._session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == self._task.id, ResearchTask.status == "running")
            .values(**values)
        )
        if result.rowcount == 0:
            logger.warning(
                "CAS 失败：最终化时任务状态已变更: task_id=%s",
                self._task.id,
            )
        await self._session.flush()

        # SSE 最终事件
        if new_status == "completed":
            self._sse.publish(EVENT_TASK_COMPLETED, {
                "task_id": str(self._task.id),
                "status": "completed",
                "trace": {
                    "total_duration_ms": (
                        int((now - self._task.started_at).total_seconds() * 1000)
                        if self._task.started_at else 0
                    ),
                    "sources": self._task.total_sources or 0,
                    "evidence": self._task.total_evidence or 0,
                },
            })
        elif new_status == "partially_completed":
            self._sse.publish(EVENT_TASK_COMPLETED, {
                "task_id": str(self._task.id),
                "status": "partially_completed",
                "trace": self._task.trace,
            })
        elif new_status == "failed":
            self._sse.publish(EVENT_TASK_FAILED, {
                "task_id": str(self._task.id),
                "error_type": error_info.get("error_code", "Unknown") if error_info else "Unknown",
                "error_description": error_info.get("error_message", "") if error_info else "",
                "recoverable": error_info.get("recoverable", False) if error_info else False,
            })

        logger.info(
            "Pipeline 完成: task_id=%s, status=%s, steps=%d, evidence=%d",
            self._task.id, new_status, len(steps), evidence_count,
        )

    async def _handle_fatal_error(self, error: Exception) -> None:
        """处理未捕获的致命错误：CAS 更新 task status 为 failed。"""
        try:
            now = datetime.now(timezone.utc)
            error_code = getattr(error, "error_code", None) or "E3999"
            error_msg = str(error)
            trace_data = self._trace.finish()

            # CAS: 仅当 status='running' 时才更新为 failed
            await self._session.execute(
                sa_update(ResearchTask)
                .where(ResearchTask.id == self._task.id, ResearchTask.status == "running")
                .values(
                    status="failed",
                    completed_at=now,
                    error_code=error_code,
                    error_message=error_msg,
                    recoverable=False,
                    trace=trace_data,
                )
            )
            await self._session.flush()

            self._sse.publish(EVENT_TASK_FAILED, {
                "task_id": str(self._task.id),
                "error_type": error.__class__.__name__,
                "error_description": error_msg,
                "recoverable": False,
            })
        except Exception as inner:
            logger.exception("写入致命错误时再次失败: %s", inner)


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
    （未注册的阶段在 Orchestrator 中自动跳过）
    """
    handlers: dict[str, PhaseFunc] = {}

    # Phase 2 stubs（§3.3-§3.5 替换为完整实现）
    try:
        from app.pipeline.planner import run_planning
        handlers["planning"] = run_planning
    except ImportError:
        logger.warning("planner.py 未找到，planning 阶段将跳过")

    try:
        from app.pipeline.searcher import run_search
        handlers["search"] = run_search
    except ImportError:
        logger.warning("searcher.py 未找到，search 阶段将跳过")

    try:
        from app.pipeline.fetcher import run_fetch
        handlers["fetch"] = run_fetch
    except ImportError:
        logger.warning("fetcher.py 未找到，fetch 阶段将跳过")

    # Phase 3（rerank / synthesis / evidence_graph / render）
    # 未注册 → Orchestrator 自动 skip

    return handlers
