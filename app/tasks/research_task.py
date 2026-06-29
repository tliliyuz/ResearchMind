"""Celery 异步任务入口 —— execute_research_task。

Worker 拾取任务后调用 PipelineOrchestrator 执行全 Pipeline。
设计对齐 ARCHITECTURE.md §3.3 / ROADMAP.md §3.2。

执行流程：
1. Celery Worker 收到 task_id
2. 获取/创建当前 Worker 进程的事件循环（避免 asyncio.run() 反复关闭 loop）
3. loop.run_until_complete() 执行异步 Pipeline
4. 创建 DB session → 加载 ResearchTask → 实例化 Orchestrator → run()
5. 顶层异常捕获 → 更新 task status 为 failed
6. 无论成功/失败，session 最终 commit
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select as sa_select, update as sa_update

from app.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import AppException, extract_recoverable_from_exception
from app.core.trace_recorder import TraceRecorder
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.agent.runtime import AgentRuntime
from app.pipeline.sse_bridge import SSEBridge
from app.services.pipeline_orchestrator import (
    PHASE_ORDER,
    PipelineOrchestrator,
    build_default_phase_handlers,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """获取当前 Worker 进程的事件循环；若未设置或已关闭则新建。"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop


@celery_app.task(
    bind=True,
    name="execute_research_task",
    max_retries=0,  # 不自动重试 —— 断点续跑由 Phase 4 Retry API 显式触发
    default_retry_delay=0,
    acks_late=True,  # 任务完成后才 ACK，防止 Worker 崩溃丢失任务
)
def execute_research_task(self, task_id: str) -> dict:
    """执行研究任务 Pipeline（Celery 任务入口）。

    由 research_service.create_task() 在 commit 后 delay 触发。

    Args:
        task_id: ResearchTask UUID 字符串

    Returns:
        {"status": "...", "task_id": "..."}
    """
    logger.info("Celery Worker 拾取任务: task_id=%s", task_id)

    loop = _get_worker_loop()
    try:
        result = loop.run_until_complete(_run_pipeline(task_id))
        logger.info("Pipeline 执行完成: task_id=%s, status=%s", task_id, result.get("status"))
        return result
    except Exception as e:
        logger.exception("Celery 任务执行异常: task_id=%s, error=%s", task_id, e)
        # 兜底：尝试写入失败状态，保留原异常的 recoverable 语义
        try:
            loop = _get_worker_loop()
            recoverable = extract_recoverable_from_exception(e)
            loop.run_until_complete(_emergency_fail(task_id, str(e), recoverable))
        except Exception:
            logger.exception("紧急写入失败状态也失败了: task_id=%s", task_id)
        # 禁止将原始异常/SQL 等内部细节返回给调用方
        return {"status": "failed", "task_id": task_id}


# ── 异步主逻辑 ──────────────────────────────────────────────


async def _build_trace_from_steps(session, task_id: str) -> dict | None:
    """从已完成步骤重建 previous_trace（用于 task.trace 为空的恢复场景）。

    当 Worker 崩溃前未完成任何 checkpoint（或旧代码未开启 checkpoint）
    导致 task.trace 为 NULL 时，从 research_steps 表中提取已完成阶段的
    耗时/token/成本数据，构建可被 TraceRecorder._preload_previous_phases()
    使用的 minimal trace dict。

    Args:
        session: DB 异步会话
        task_id: 任务 UUID

    Returns:
        minimal trace dict 或 None（无已完成步骤时）
    """
    result = await session.execute(
        sa_select(ResearchStep)
        .where(
            ResearchStep.task_id == task_id,
            ResearchStep.step_type.in_(PHASE_ORDER),
            ResearchStep.status.in_(["completed", "skipped"]),
        )
        .order_by(ResearchStep.completed_at)
    )
    steps = result.scalars().all()

    if not steps:
        return None

    phases: dict = {}
    phase_durations: dict = {}

    for step in steps:
        phase_name = step.step_type

        # 同一 Phase 可能有多条记录（如子 step），保留最新的
        existing = phases.get(phase_name)
        if existing is not None:
            existing_dur = int(existing.get("duration_ms") or 0)
            current_dur = step.duration_ms or 0
            if current_dur <= existing_dur:
                continue

        output = step.output or {}
        cost = step.cost or {}

        phase_data: dict = {
            "duration_ms": step.duration_ms or 0,
        }

        # Token 数据：优先取 output 中的 LLM 统计，回退到 cost 字段
        in_tok = int(output.get("prompt_tokens") or cost.get("input_tokens") or 0)
        out_tok = int(output.get("completion_tokens") or cost.get("output_tokens") or 0)
        model = output.get("model") or cost.get("model")

        if in_tok or out_tok or model:
            phase_data["input_tokens"] = in_tok
            phase_data["output_tokens"] = out_tok
            if model:
                phase_data["model"] = model

        # 直接成本（search / fetch 等非 LLM 阶段）
        if cost.get("estimated_cost_usd") is not None:
            phase_data["cost_usd"] = float(cost["estimated_cost_usd"])
        elif output.get("search_cost_usd") is not None:
            phase_data["cost_usd"] = float(output["search_cost_usd"])
        elif output.get("fetch_cost_usd") is not None:
            phase_data["cost_usd"] = float(output["fetch_cost_usd"])

        phases[phase_name] = phase_data
        phase_durations[phase_name] = step.duration_ms or 0

    if not phases:
        return None

    return {
        "phases": phases,
        "phase_durations_ms": phase_durations,
    }


async def _run_pipeline(task_id: str) -> dict:
    """异步 Pipeline 执行体（在 Worker 持久事件循环中运行）。

    Steps:
    1. 打开 DB session
    2. 加载 ResearchTask（含幂等检查：非 pending 则跳过）
    3. 实例化 SSEBridge + TraceRecorder + Orchestrator
    4. 执行 Pipeline
    5. Commit
    """
    async with async_session_factory() as session:
        # 1. 加载任务
        task = await session.get(ResearchTask, task_id)
        if task is None:
            logger.error("任务不存在: task_id=%s", task_id)
            return {"status": "error", "task_id": task_id, "reason": "TaskNotFound"}

        # 幂等检查：pending → 正常执行；running → Worker 崩溃恢复；终态 → 跳过
        if task.status == "running":
            logger.warning(
                "任务处于 running，按 Worker 崩溃恢复继续执行: task_id=%s",
                task_id,
            )
        elif task.status != "pending":
            logger.warning(
                "任务非 pending/running 状态，跳过执行: task_id=%s, status=%s",
                task_id, task.status,
            )
            return {"status": "skipped", "task_id": task_id, "reason": f"status={task.status}"}

        # 2. 实例化依赖
        sse_bridge = SSEBridge(task_id)

        # 断点续跑：传入上一次运行的 trace，使续跑中被跳过的阶段保留记录，
        # 并将两次运行的 tokens / cost 累加到 task 总计。
        # 若 task.trace 为空（旧代码未 checkpoint 或崩溃前未完成任何 Phase），
        # 则从 research_steps 表的已完成记录重建 previous_trace 作为退路。
        previous_trace = task.trace
        if not isinstance(previous_trace, dict) and task.status == "running":
            previous_trace = await _build_trace_from_steps(session, task_id)
            if previous_trace:
                logger.info(
                    "task.trace 为空，已从 %d 个已完成步骤重建 previous_trace: task_id=%s",
                    len(previous_trace.get("phases", {})),
                    task_id,
                )
        trace_recorder = TraceRecorder(
            task_id=task_id,
            user_id=task.user_id,
            topic=task.topic,
            previous_trace=previous_trace,
        )
        # 3. 根据 feature flag 选择执行引擎
        if settings.USE_AGENT_RUNTIME:
            runtime = AgentRuntime.build_default(
                task=task,
                session=session,
                sse_bridge=sse_bridge,
                trace_recorder=trace_recorder,
            )
            await runtime.run()
        else:
            phase_handlers = build_default_phase_handlers()
            orchestrator = PipelineOrchestrator(
                task=task,
                session=session,
                sse_bridge=sse_bridge,
                trace_recorder=trace_recorder,
                phase_handlers=phase_handlers,
            )
            await orchestrator.run()

        # 4. 提交全部变更（Step 状态 + Execution Context + Task 状态）
        await session.commit()

        # 5. 刷新内存对象：Orchestrator 内部可能通过 update 直接修改 DB，
        #    避免返回 stale 状态或触发懒加载异常
        await session.refresh(task)

        return {"status": task.status, "task_id": task_id}


# ── 紧急失败写入 ────────────────────────────────────────────


async def _emergency_fail(task_id: str, error_msg: str | None = None, recoverable: bool = False) -> bool:
    """兜底：在 Pipeline 完全崩溃时写入失败状态。

    独立 session，不依赖 Orchestrator 或任何可能出错的对象。
    使用 CAS 仅当 status 为 pending/running 时才更新为 failed，避免覆盖终态。

    Args:
        error_msg: 原始异常描述，仅用于服务端日志排查，不会写入 task.error_message。

    Returns:
        bool: CAS 成功返回 True，失败返回 False。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_update(ResearchTask)
            .where(
                ResearchTask.id == task_id,
                ResearchTask.status.in_(["pending", "running"]),
            )
            .values(
                status="failed",
                completed_at=datetime.now(timezone.utc),
                error_code="E3999",
                # 禁止将原始异常/SQL/堆栈暴露给前端，统一使用兜底文案
                error_message="未预期的内部错误，请稍后重试",
                recoverable=recoverable,
            )
        )
        await session.commit()
        updated = result.rowcount > 0
        if not updated:
            logger.warning("紧急失败写入 CAS 失败，任务已非 pending/running: task_id=%s", task_id)
        elif error_msg:
            logger.warning(
                "紧急失败原始信息（服务端记录）: task_id=%s, error=%s",
                task_id, error_msg[:1000],
            )
        return updated
