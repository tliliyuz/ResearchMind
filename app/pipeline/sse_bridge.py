"""SSE Bridge — Redis Pub/Sub 桥接 Celery Worker ↔ FastAPI ↔ SSE Stream

两层 API：

发布层（Celery Worker 同步调用）：
  SSEBridge(task_id) → bridge.publish(event_type, data)
  事件通过 Redis PUBLISH 发送到 rm:sse:{task_id} 频道，带 seq 序号。

订阅层（FastAPI 异步调用）：
  sse_event_stream(task_id) → AsyncIterator[str]
  订阅 Redis 频道，yield SSE 格式事件字符串。
  连接时立即推送 task.status.snapshot（需调用方提供快照数据）。

复用 app.core.sse 的 format_sse_event / stream_with_heartbeat。
"""

import asyncio
import json
import logging
import sys
from typing import AsyncIterator

from app.config import settings
from app.core.redis_client import get_redis, get_async_redis
from app.core.sse import format_sse_event, stream_with_heartbeat

logger = logging.getLogger(__name__)

# ── Redis 频道前缀 ─────────────────────────────────────────
CHANNEL_PREFIX = "rm:sse"


def _build_channel(task_id: str) -> str:
    """构建 SSE Redis 频道名。"""
    return f"{CHANNEL_PREFIX}:{task_id}"


# ── 事件类型常量（对齐 API.md §4.1）───────────────────────

EVENT_TASK_CREATED = "task.created"
EVENT_TASK_STATUS_SNAPSHOT = "task.status.snapshot"
EVENT_TASK_PROGRESS = "task.progress"
EVENT_TASK_WARNING = "task.warning"
EVENT_TASK_COMPLETED = "task.completed"
EVENT_TASK_FAILED = "task.failed"
EVENT_TASK_CANCELED = "task.canceled"
EVENT_PHASE_STARTED = "phase.started"
EVENT_PHASE_COMPLETED = "phase.completed"
EVENT_STEP_STARTED = "step.started"
EVENT_STEP_PROGRESS = "step.progress"
EVENT_STEP_COMPLETED = "step.completed"
EVENT_STEP_FAILED = "step.failed"
EVENT_STEP_SKIPPED = "step.skipped"
EVENT_CHECKPOINT_SAVED = "checkpoint.saved"

# [v2] 预留
# EVENT_TASK_PAUSED = "task.paused"
# EVENT_TASK_RESUMED = "task.resumed"


# ═════════════════════════════════════════════════════════════
# 发布层：Celery Worker 使用（同步）
# ═════════════════════════════════════════════════════════════


class SSEBridge:
    """SSE 事件发布器 —— 供 Celery Worker 同步使用。

    每个 task 一个实例，seq 序号单调递增，保证事件有序。

    Usage:
        bridge = SSEBridge(task_id)
        bridge.publish(EVENT_TASK_CREATED, {"task_id": task_id, "status": "running"})
        bridge.publish(EVENT_STEP_COMPLETED, {"step_id": step_id, "output": {...}})
    """

    def __init__(self, task_id: str):
        self._task_id = task_id
        self._channel = _build_channel(task_id)
        self._seq = 0

    @property
    def seq(self) -> int:
        """当前 seq 序号（只读）。"""
        return self._seq

    def publish(self, event_type: str, data: dict | None = None) -> None:
        """同步发布事件到 Redis Pub/Sub。

        Args:
            event_type: 事件类型（使用 EVENT_* 常量）
            data: 事件数据字典（不含 seq，seq 自动注入）
        """
        self._seq += 1
        payload = {
            "event": event_type,
            "data": data or {},
            "seq": self._seq,
        }
        message = json.dumps(payload, ensure_ascii=False)
        try:
            get_redis().publish(self._channel, message)
        except Exception:
            logger.warning(
                "SSE 发布失败（Redis 可能不可用）: task_id=%s, event=%s, seq=%d",
                self._task_id, event_type, self._seq,
            )


# ═════════════════════════════════════════════════════════════
# 订阅层：FastAPI SSE 端点使用（异步）
# ═════════════════════════════════════════════════════════════


async def sse_event_stream(
    task_id: str,
    initial_snapshot: dict | None = None,
) -> AsyncIterator[str]:
    """异步 SSE 事件流生成器 —— 供 FastAPI StreamingResponse 使用。

    1. 连接时立即推送 task.status.snapshot（如果提供）
    2. 订阅 Redis rm:sse:{task_id} 频道
    3. 解析消息 → 组装 SSE 格式 → yield
    4. 客户端断开时自动清理订阅

    Args:
        task_id: 研究任务 ID
        initial_snapshot: 初始状态快照数据（None 则跳过 snapshot 推送）

    Yields:
        SSE 格式字符串（event + data + 心跳）
    """
    channel = _build_channel(task_id)

    async def _event_generator() -> AsyncIterator[str]:
        """内部事件生成器：snapshot + Redis Pub/Sub 消息。"""
        # 1. 连接时立即推送状态快照
        if initial_snapshot:
            yield format_sse_event(
                EVENT_TASK_STATUS_SNAPSHOT,
                initial_snapshot,
            )

        # 2. 订阅 Redis Pub/Sub
        redis_async = await get_async_redis()
        pubsub = await _subscribe_channel(redis_async, channel)
        if pubsub is None:
            logger.warning(
                "SSE 订阅失败（无法订阅 Redis 频道）: task_id=%s", task_id
            )
            return

        try:
            # 3. 循环获取消息
            while True:
                message = await _get_pubsub_message(pubsub, timeout=1.0)
                if message is None:
                    continue  # 超时 → 继续等待（心跳由 stream_with_heartbeat 处理）

                # 仅处理 "message" 类型（忽略 subscribe/unsubscribe 确认等）
                if message.get("type") != "message":
                    continue

                data_str = message.get("data", "")
                if not data_str:
                    continue

                try:
                    payload = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning("SSE 消息 JSON 解析失败: %s", data_str[:100])
                    continue

                event_type = payload.get("event", "unknown")
                event_data = payload.get("data", {})

                yield format_sse_event(event_type, event_data)

        except asyncio.CancelledError:
            logger.debug("SSE 订阅已取消: task_id=%s", task_id)
        finally:
            await _unsubscribe_channel(pubsub, channel)

    # 4. 用 stream_with_heartbeat 包裹（自动插入心跳帧）
    async for formatted in stream_with_heartbeat(_event_generator()):
        yield formatted


# ── 平台适配的 Pub/Sub 辅助函数 ────────────────────────────

_IS_LINUX = sys.platform != "win32"


async def _subscribe_channel(
    redis_async,
    channel: str,
):
    """订阅 Redis 频道（跨平台）。

    - Linux (redis.asyncio): 原生 pubsub，性能最优
    - Windows (ThreadedRedisClient): 使用同步 pubsub + 线程池

    Returns:
        - Linux: redis.asyncio.client.PubSub 实例
        - Windows: _SyncPubSubWrapper 实例
        - None: 订阅失败
    """
    if _IS_LINUX:
        try:
            pubsub = redis_async.pubsub()
            await pubsub.subscribe(channel)
            logger.debug("SSE 订阅成功 (native async): channel=%s", channel)
            return pubsub
        except Exception as e:
            logger.error("SSE 订阅失败 (native async): %s", e)
            return None
    else:
        # Windows: 使用同步 Redis 的 pubsub + 线程池
        try:
            sync_redis = get_redis()
            pubsub = sync_redis.pubsub()
            pubsub.subscribe(channel)
            wrapper = _SyncPubSubWrapper(pubsub)
            logger.debug("SSE 订阅成功 (sync wrapper): channel=%s", channel)
            return wrapper
        except Exception as e:
            logger.error("SSE 订阅失败 (sync wrapper): %s", e)
            return None


async def _get_pubsub_message(pubsub, timeout: float = 1.0) -> dict | None:
    """从 PubSub 获取下一条消息（跨平台，非阻塞）。

    Args:
        pubsub: _subscribe_channel 返回的实例
        timeout: 等待超时秒数

    Returns:
        消息字典 或 None（超时/无消息）
    """
    if _IS_LINUX:
        try:
            return await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=timeout
            )
        except Exception:
            return None
    else:
        # Windows: 通过线程池调用同步 pubsub.get_message
        if isinstance(pubsub, _SyncPubSubWrapper):
            return await pubsub.get_message(timeout=timeout)
        return None


async def _unsubscribe_channel(pubsub, channel: str) -> None:
    """取消订阅并关闭连接。"""
    try:
        if _IS_LINUX:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        elif isinstance(pubsub, _SyncPubSubWrapper):
            await pubsub.unsubscribe(channel)
    except Exception as e:
        logger.warning("SSE 取消订阅异常: %s", e)


class _SyncPubSubWrapper:
    """同步 Redis PubSub 的异步包装器（Windows 开发环境使用）。

    通过 asyncio.to_thread 将阻塞的 pubsub.get_message()
    委托到线程池执行，避免阻塞 FastAPI 事件循环。
    """

    def __init__(self, pubsub):
        self._pubsub = pubsub

    async def get_message(self, timeout: float = 1.0) -> dict | None:
        """异步获取下一条 Pub/Sub 消息。"""
        return await asyncio.to_thread(
            self._pubsub.get_message,
            ignore_subscribe_messages=True,
            timeout=timeout,
        )

    async def unsubscribe(self, channel: str) -> None:
        """异步取消订阅。"""
        await asyncio.to_thread(self._pubsub.unsubscribe, channel)
        await asyncio.to_thread(self._pubsub.close)
