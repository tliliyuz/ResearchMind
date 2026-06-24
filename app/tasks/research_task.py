"""Celery 异步任务入口 —— execute_research_task。

Worker 拾取任务后调用 PipelineOrchestrator 执行全 Pipeline。
设计对齐 ARCHITECTURE.md §3.3 / ROADMAP.md §3.2。

执行流程：
1. Celery Worker 收到 task_id
2. asyncio.run() 包裹异步逻辑
3. 创建 DB session → 加载 ResearchTask → 实例化 Orchestrator → run()
4. 顶层异常捕获 → 更新 task status 为 failed
5. 无论成功/失败，session 最终 commit
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import AppException
from app.core.trace_recorder import TraceRecorder
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import SSEBridge
from app.services.pipeline_orchestrator import (
    PipelineOrchestrator,
    build_default_phase_handlers,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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

    try:
        result = asyncio.run(_run_pipeline(task_id))
        logger.info("Pipeline 执行完成: task_id=%s, status=%s", task_id, result.get("status"))
        return result
    except Exception as e:
        logger.exception("Celery 任务执行异常: task_id=%s, error=%s", task_id, e)
        # 兜底：尝试同步写入失败状态
        try:
            asyncio.run(_emergency_fail(task_id, str(e)))
        except Exception:
            logger.exception("紧急写入失败状态也失败了: task_id=%s", task_id)
        return {"status": "failed", "task_id": task_id, "error": str(e)}


# ── 异步主逻辑 ──────────────────────────────────────────────


async def _run_pipeline(task_id: str) -> dict:
    """异步 Pipeline 执行体（在 asyncio.run() 中运行）。

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

        # 幂等检查：非 pending 状态 → 跳过（可能已被其他 Worker 拾取或已取消）
        if task.status != "pending":
            logger.warning(
                "任务非 pending 状态，跳过执行: task_id=%s, status=%s",
                task_id, task.status,
            )
            return {"status": "skipped", "task_id": task_id, "reason": f"status={task.status}"}

        # 2. 实例化依赖
        sse_bridge = SSEBridge(task_id)
        trace_recorder = TraceRecorder(
            task_id=task_id,
            user_id=str(task.user_id),
            topic=task.topic,
        )
        phase_handlers = build_default_phase_handlers()

        orchestrator = PipelineOrchestrator(
            task=task,
            session=session,
            sse_bridge=sse_bridge,
            trace_recorder=trace_recorder,
            phase_handlers=phase_handlers,
        )

        # 3. 执行 Pipeline
        await orchestrator.run()

        # 4. 提交全部变更（Step 状态 + Execution Context + Task 状态）
        await session.commit()

        return {"status": task.status, "task_id": task_id}


# ── 紧急失败写入 ────────────────────────────────────────────


async def _emergency_fail(task_id: str, error_msg: str) -> None:
    """兜底：在 Pipeline 完全崩溃时写入失败状态。

    独立 session，不依赖 Orchestrator 或任何可能出错的对象。
    """
    async with async_session_factory() as session:
        task = await session.get(ResearchTask, task_id)
        if task is None:
            return
        task.status = "failed"
        task.completed_at = datetime.now(timezone.utc)
        task.error_code = "E3999"
        task.error_message = f"Celery Worker 未捕获异常: {error_msg[:500]}"
        task.recoverable = False
        await session.commit()
