"""后台异步采集器。

定期刷新 Celery 队列长度、Worker 在线数、Worker 活跃任务数等 Gauge 指标。
采集异常仅记录日志，不影响主应用。
"""

from __future__ import annotations

import asyncio
import logging

import redis

from app.config import settings
from app.metrics.emitters import (
    set_celery_queue_length,
    set_celery_worker_tasks_active,
    set_celery_workers_active,
)

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Prometheus Gauge 指标后台采集器。"""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._redis_client: redis.Redis | None = None

    async def start(self) -> None:
        """启动后台采集循环。"""
        if not settings.METRICS_ENABLED:
            logger.info("Metrics 已禁用，跳过后台采集器启动")
            return

        try:
            self._redis_client = redis.from_url(
                settings.CELERY_BROKER_URL,
                decode_responses=True,
            )
        except Exception:
            logger.exception("MetricsCollector Redis 客户端初始化失败")
            self._redis_client = None

        self._task = asyncio.create_task(self._run())
        logger.info("MetricsCollector 已启动")

    async def stop(self) -> None:
        """停止后台采集循环。"""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._redis_client is not None:
            try:
                self._redis_client.close()
            except Exception:
                logger.warning("MetricsCollector Redis 关闭异常", exc_info=True)
            self._redis_client = None
        logger.info("MetricsCollector 已停止")

    async def _run(self) -> None:
        """主循环：按配置间隔交替刷新队列与 Worker 指标。"""
        queue_interval = max(1, settings.METRICS_QUEUE_REFRESH_INTERVAL)
        worker_interval = max(1, settings.METRICS_WORKER_REFRESH_INTERVAL)

        queue_deadline = asyncio.get_event_loop().time()
        worker_deadline = queue_deadline

        while True:
            now = asyncio.get_event_loop().time()

            if now >= queue_deadline:
                await self._refresh_queue_length()
                queue_deadline = now + queue_interval

            if now >= worker_deadline:
                await self._refresh_workers()
                worker_deadline = now + worker_interval

            # 取最近一个deadline作为下次唤醒时间
            sleep_until = min(queue_deadline, worker_deadline)
            sleep_seconds = sleep_until - asyncio.get_event_loop().time()
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

    async def _refresh_queue_length(self) -> None:
        """刷新队列长度 Gauge。"""
        if self._redis_client is None:
            return
        try:
            from app.tasks.celery_app import celery_app

            queue = celery_app.conf.task_default_queue
            length = await asyncio.to_thread(self._redis_client.llen, queue)
            set_celery_queue_length(queue, int(length))
        except Exception:
            logger.warning("刷新队列长度失败", exc_info=True)

    async def _refresh_workers(self) -> None:
        """刷新 Worker 在线数与活跃任务数 Gauge。"""
        try:
            from app.tasks.celery_app import celery_app

            inspect = celery_app.control.inspect(timeout=settings.METRICS_WORKER_PING_TIMEOUT)

            pings = await asyncio.to_thread(inspect.ping)
            pings = pings or {}
            set_celery_workers_active(len(pings))

            active = await asyncio.to_thread(inspect.active)
            active = active or {}
            total_active = sum(len(tasks) for tasks in active.values())
            set_celery_worker_tasks_active(total_active)
        except Exception:
            logger.warning("刷新 Worker 指标失败", exc_info=True)
