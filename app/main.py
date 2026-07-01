"""
ResearchMind FastAPI 入口。

- 创建 FastAPI 实例，配置 CORS 中间件
- 注册全局异常处理器
- 提供 /api/health 健康检查端点
- 后续 Phase 引入路由（auth / research）
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select as sa_select, update as sa_update

from app.config import settings
from app.core.database import async_session_factory
from app.core.exceptions import AppException
from app.core.logging_config import setup_logging
from app.metrics import (
    CONTENT_TYPE_LATEST,
    emit_task_status_transition,
    get_metrics_output,
    setup_metrics,
    shutdown_metrics,
)
from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.rate_limit_middleware import RateLimitMiddleware
from app.middleware.request_id_middleware import RequestIDMiddleware
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import EVENT_TASK_FAILED, SSEBridge
from app.tasks.celery_app import celery_app
from app.tasks.lock import check_task_lock_async
from app.tasks.recovery import recover_stale_tasks

logger = logging.getLogger(__name__)


# ── 生命周期管理 ──────────────────────────────────────────


async def _recover_stale_tasks() -> None:
    """启动时恢复过时 running 任务。

    调用 recover_stale_tasks(check_lock=False) 按时间阈值兜底恢复，
    失败不阻塞应用启动。
    """
    try:
        recovered = await recover_stale_tasks(check_lock=False)
        if recovered:
            logger.warning(
                "启动恢复：已重新投递 %d 个过时 running 任务: %s",
                len(recovered), recovered,
            )
    except Exception:
        logger.exception("启动时过时任务恢复失败，不阻塞应用启动")


# 内存追踪：task_id → 首次发现任务级锁缺失的 UTC 时间
_worker_lock_missing_since: dict[str, datetime] = {}


async def _mark_task_worker_timeout(task_id: str) -> None:
    """将任务标记为 Worker 超时失败（E3112，可恢复）。

    使用 CAS 仅当 status='running' 时更新为 failed，并通过 SSE 推送 task.failed。
    """
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        result = await session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.status == "running")
            .values(
                status="failed",
                completed_at=now,
                error_code="E3112",
                error_message="Worker 响应超时，请稍后重试",
                recoverable=True,
            )
        )
        await session.commit()
        updated = result.rowcount > 0

    if not updated:
        logger.warning(
            "Worker 超时标记失败 CAS 未命中，任务已非 running: task_id=%s", task_id
        )
        return

    logger.warning("Worker 超时，任务已标记为 failed: task_id=%s", task_id)

    emit_task_status_transition("failed", recoverable=True, error_code="E3112")

    try:
        # 读取 last_checkpoint 供前端断点续跑
        async with async_session_factory() as session:
            row = await session.execute(
                sa_select(ResearchTask.execution_context).where(ResearchTask.id == task_id)
            )
            execution_context = row.scalar_one_or_none() or {}
    except Exception:
        logger.exception("读取 execution_context 失败: task_id=%s", task_id)
        execution_context = {}

    last_checkpoint = None
    if isinstance(execution_context, dict):
        last_checkpoint = execution_context.get("last_completed_step_id")

    payload = {
        "task_id": task_id,
        "error_type": "E3112",
        "error_description": "Worker 响应超时，请稍后重试",
        "recoverable": True,
    }
    if last_checkpoint:
        payload["last_checkpoint"] = str(last_checkpoint)

    try:
        sse = SSEBridge(task_id)
        await sse.publish(EVENT_TASK_FAILED, payload)
    except Exception:
        logger.exception("Worker 超时 task.failed SSE 推送失败: task_id=%s", task_id)


async def _mark_task_pending_timeout(task_id: str) -> None:
    """将长时间 pending 的任务标记为 Worker 未拾取失败（E3113，可恢复）。

    使用 CAS 仅当 status='pending' 时更新为 failed，并通过 SSE 推送 task.failed。
    """
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        result = await session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.status == "pending")
            .values(
                status="failed",
                completed_at=now,
                error_code="E3113",
                error_message="Worker 未拾取任务，请稍后重试",
                recoverable=True,
            )
        )
        await session.commit()
        updated = result.rowcount > 0

    if not updated:
        logger.warning(
            "Pending 超时标记失败 CAS 未命中，任务已非 pending: task_id=%s", task_id
        )
        return

    logger.warning("Pending 任务超时，已标记为 failed: task_id=%s", task_id)

    emit_task_status_transition("failed", recoverable=True, error_code="E3113")

    payload = {
        "task_id": task_id,
        "error_type": "E3113",
        "error_description": "Worker 未拾取任务，请稍后重试",
        "recoverable": True,
    }

    try:
        sse = SSEBridge(task_id)
        await sse.publish(EVENT_TASK_FAILED, payload)
    except Exception:
        logger.exception("Pending 超时 task.failed SSE 推送失败: task_id=%s", task_id)


async def _check_worker_timeouts() -> None:
    """扫描 running 任务的锁状态 + pending 任务是否被 Worker 拾取，超时后标记失败。"""
    global _worker_lock_missing_since

    grace_threshold = datetime.now(timezone.utc) - timedelta(
        seconds=settings.WORKER_TIMEOUT_GRACE_SECONDS
    )
    pending_threshold = datetime.now(timezone.utc) - timedelta(
        seconds=settings.PENDING_TASK_TIMEOUT_SECONDS
    )

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                sa_select(ResearchTask.id, ResearchTask.started_at)
                .where(ResearchTask.status == "running")
            )
            running_tasks = list(result.all())

            # 同时扫描长时间未被 Worker 拾取的 pending 任务
            # started_at 在 create_task / retry_task 时设置为 now，
            # 若 PENDING_TASK_TIMEOUT_SECONDS 后仍为 pending，说明无 Worker 在线
            pending_result = await session.execute(
                sa_select(ResearchTask.id)
                .where(
                    ResearchTask.status == "pending",
                    ResearchTask.started_at.is_not(None),
                    ResearchTask.started_at < pending_threshold,
                )
            )
            stale_pending_ids = [str(row[0]) for row in pending_result.all()]
    except Exception:
        logger.exception("扫描任务状态失败")
        return

    now = datetime.now(timezone.utc)
    tracked_ids = set(_worker_lock_missing_since.keys())
    current_ids = set()

    for task_id, started_at in running_tasks:
        task_id = str(task_id)
        current_ids.add(task_id)

        # 启动宽限期内跳过（避免任务刚创建/锁未写入时被误判）
        if started_at and started_at > grace_threshold:
            _worker_lock_missing_since.pop(task_id, None)
            continue

        try:
            lock_exists = await check_task_lock_async(task_id)
        except Exception:
            # Redis 不可用时不应误判任务失败，跳过本次检查
            logger.warning("检查任务级锁异常，跳过本次判定: task_id=%s", task_id)
            _worker_lock_missing_since.pop(task_id, None)
            continue

        if lock_exists:
            _worker_lock_missing_since.pop(task_id, None)
            continue

        # 锁缺失：记录首次发现时间
        first_seen = _worker_lock_missing_since.get(task_id)
        if first_seen is None:
            _worker_lock_missing_since[task_id] = now
            logger.warning("任务级锁缺失，开始计时: task_id=%s", task_id)
            continue

        elapsed = (now - first_seen).total_seconds()
        if elapsed >= settings.WORKER_TIMEOUT_SECONDS:
            await _mark_task_worker_timeout(task_id)
            _worker_lock_missing_since.pop(task_id, None)

    # 清理已非 running 任务的残留追踪
    for stale_id in tracked_ids - current_ids:
        _worker_lock_missing_since.pop(stale_id, None)

    # 标记长时间未被 Worker 拾取的 pending 任务
    for task_id in stale_pending_ids:
        await _mark_task_pending_timeout(task_id)


async def _run_worker_timeout_watcher() -> None:
    """Worker 超时监察者后台协程。

    定期检查 running 任务的任务级锁，锁缺失持续 WORKER_TIMEOUT_SECONDS 后
    自动标记任务为 failed（E3112，recoverable=True），并推送 task.failed。
    """
    logger.info(
        "启动 Worker 超时监察者: interval=%ss, timeout=%ss",
        settings.WORKER_TIMEOUT_CHECK_INTERVAL,
        settings.WORKER_TIMEOUT_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(settings.WORKER_TIMEOUT_CHECK_INTERVAL)
            await _check_worker_timeouts()
        except asyncio.CancelledError:
            logger.info("Worker 超时监察者已停止")
            break
        except Exception:
            logger.exception("Worker 超时监察者异常")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动 / 关闭时的生命周期事件。"""
    logger.info(f"🚀 {settings.APP_NAME} v0.1.0 启动中... (env={settings.ENV}, debug={settings.DEBUG})")
    await setup_metrics()
    await _recover_stale_tasks()
    watcher_task = asyncio.create_task(_run_worker_timeout_watcher())
    yield
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    await shutdown_metrics()
    logger.info(f"👋 {settings.APP_NAME} 已关闭")


# ── 结构化日志（JSON 格式 + request_id 链路追踪） ──────────

setup_logging(debug=settings.DEBUG)

# ── FastAPI 实例 ──────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS 中间件 ───────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request ID 中间件（链路追踪 contextvars 注入） ─────────

app.add_middleware(RequestIDMiddleware)

# ── Auth 中间件（JWT 验证，写入 request.state） ──────────────

app.add_middleware(AuthMiddleware)

# ── 限流中间件（固定窗口计数器 + Redis 原子操作） ───────────

app.add_middleware(RateLimitMiddleware)

# ── 全局异常处理器 ───────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 请求校验失败 → E9003 (422)。"""
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    return JSONResponse(
        status_code=422,
        content={
            "code": "E9003",
            "message": "请求参数校验失败",
            "detail": {
                "error_type": "ValidationError",
                "error_description": "请求参数校验失败，请检查输入",
                "errors": errors,
            },
        },
    )


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """AppException → 对应 HTTP 状态码。

    AppException 已通过 HTTPException.detail 携带完整响应体
    （{"code", "message", "detail"}），Starlette 对 dict 类型的 detail
    直接作为 JSON 响应体返回。
    """
    logger.warning(
        "业务异常: code=%s, message=%s, status=%d",
        exc.error_code, exc.error_message, exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常 → E9001 (500)。"""
    logger.exception(f"未预料的服务器内部错误: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "code": "E9001",
            "message": "服务器内部错误",
            "detail": {
                "error_type": "InternalError",
                "error_description": "服务器内部错误，请稍后重试",
            },
        },
    )


# ── 健康检查 ─────────────────────────────────────────────


@app.get("/api/health", tags=["系统"])
async def health_check():
    """健康检查端点。"""
    return {
        "code": "0",
        "message": "ok",
        "data": {"status": "healthy"},
    }


@app.get("/api/health/workers", tags=["系统"])
async def worker_health_check():
    """Worker 集群健康检查端点。"""
    try:
        pings = celery_app.control.ping(timeout=5.0) or []
    except Exception as e:
        logger.exception("Worker 健康检查失败")
        return {
            "code": "0",
            "message": "ok",
            "data": {
                "status": "unknown",
                "worker_count": 0,
                "workers": [],
                "error": str(e),
            },
        }

    workers = []
    for ping in pings:
        if isinstance(ping, dict):
            workers.extend(ping.keys())

    status = "healthy" if workers else "no_workers"
    return {
        "code": "0",
        "message": "ok",
        "data": {
            "status": status,
            "worker_count": len(workers),
            "workers": workers,
        },
    }


# ── Metrics 端点 ──────────────────────────────────────────


@app.get(settings.METRICS_ENDPOINT, include_in_schema=False)
async def metrics_endpoint():
    """Prometheus 指标抓取端点。"""
    return Response(content=get_metrics_output(), media_type=CONTENT_TYPE_LATEST)


# ── 路由注册 ──────────────────────────────────────────────
from app.api import auth, research

app.include_router(auth.router, prefix="/api/auth")
app.include_router(research.router, prefix="/api/research")
