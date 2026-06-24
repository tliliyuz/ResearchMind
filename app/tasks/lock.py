"""
Celery Step 幂等锁 — 基于 Redis SET NX 的原子锁。

防止同一 Step 被重复入队（Worker 并发 / 重试风暴 / 消息重复投递）。
锁 Key 格式：`rm:idempotency:{task_id}:{step_type}`，TTL 默认 600s。

使用方式：
    from app.tasks.lock import acquire_step_lock, release_step_lock

    if not acquire_step_lock(task_id, "planning"):
        logger.warning("Step 已锁定，跳过重复入队")
        return

    try:
        run_planning(task_id)
    finally:
        release_step_lock(task_id, "planning")
"""

from app.config import settings
from app.core.redis_client import get_redis

# Redis Key 前缀
KEY_PREFIX = "rm:idempotency"


def _build_lock_key(task_id: str, step_type: str) -> str:
    """构建幂等锁 Redis key。"""
    return f"{KEY_PREFIX}:{task_id}:{step_type}"


def acquire_step_lock(
    task_id: str,
    step_type: str,
    ttl: int | None = None,
) -> bool:
    """尝试获取 Step 幂等锁（同步，供 Celery 任务使用）。

    Args:
        task_id: 研究任务 UUID
        step_type: Step 类型（planning / search / fetch / rerank / synthesis / evidence_graph / render）
        ttl: 锁过期时间（秒），默认读取 CELERY_IDEMPOTENCY_LOCK_TTL

    Returns:
        True:  获取成功，可继续执行
        False: 锁已被占用，应跳过（防重复入队）
    """
    if ttl is None:
        ttl = settings.CELERY_IDEMPOTENCY_LOCK_TTL

    key = _build_lock_key(task_id, step_type)
    return bool(get_redis().set(key, "locked", ex=ttl, nx=True))


def release_step_lock(task_id: str, step_type: str) -> None:
    """释放 Step 幂等锁（同步，Step 完成/失败后调用，幂等操作）。"""
    key = _build_lock_key(task_id, step_type)
    get_redis().delete(key)


def check_step_lock(task_id: str, step_type: str) -> bool:
    """检查 Step 幂等锁是否存在。

    Returns:
        True:  已锁定
        False: 未锁定
    """
    key = _build_lock_key(task_id, step_type)
    return get_redis().exists(key) > 0


async def acquire_step_lock_async(
    task_id: str,
    step_type: str,
    ttl: int | None = None,
) -> bool:
    """异步版 Step 幂等锁获取，供 async 上下文使用（避免阻塞事件循环）。"""
    if ttl is None:
        ttl = settings.CELERY_IDEMPOTENCY_LOCK_TTL

    from app.core.redis_client import get_async_redis

    key = _build_lock_key(task_id, step_type)
    redis_client = await get_async_redis()
    return bool(await redis_client.set(key, "locked", ex=ttl, nx=True))


async def release_step_lock_async(task_id: str, step_type: str) -> None:
    """异步版 Step 幂等锁释放。"""
    from app.core.redis_client import get_async_redis

    key = _build_lock_key(task_id, step_type)
    redis_client = await get_async_redis()
    await redis_client.delete(key)
