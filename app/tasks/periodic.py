"""
Celery Beat 定时任务 —— 数据 TTL 清理。

任务：
- cleanup_old_research_tasks: 删除已完成超过 N 天的研究任务（DB 级联删除子表 + Redis 孤儿锁清理）
- cleanup_stale_refresh_tokens: 删除已过期或已吊销的刷新令牌

调度入口：app/tasks/celery_app.py 的 beat_schedule。
"""

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import select as sa_select, delete as sa_delete

from app.config import settings
from app.core.database import async_session_factory
from app.core.redis_client import get_redis
from app.models.research_task import ResearchTask
from app.models.refresh_token import RefreshToken
from app.tasks.celery_app import celery_app
from app.tasks.lock import TASK_LOCK_PREFIX, KEY_PREFIX

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.periodic.cleanup_old_research_tasks", bind=True, max_retries=3)
def cleanup_old_research_tasks(self, max_age_days: int | None = None) -> dict:
    """清理已完成超过 max_age_days 天的研究任务。

    数据库层面通过 ON DELETE CASCADE 自动清理关联子表；
    任务完成后顺带扫描并删除对应任务 ID 的 Redis 孤儿锁 Key。

    Args:
        max_age_days: 任务保留天数，默认读取 CLEANUP_TASK_MAX_AGE_DAYS 或 30

    Returns:
        {"deleted_tasks": int, "orphan_lock_keys_removed": int}
    """
    if max_age_days is None:
        max_age_days = getattr(settings, "CLEANUP_TASK_MAX_AGE_DAYS", 30)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    logger.info("[cleanup] 开始清理 completed_at < %s 的研究任务", cutoff.isoformat())

    deleted_count = 0
    try:
        import asyncio

        deleted_count = asyncio.run(_delete_old_tasks(cutoff))
    except Exception as exc:
        logger.exception("[cleanup] 清理旧研究任务失败")
        raise self.retry(exc=exc, countdown=60) from exc

    # 清理孤儿 Redis 锁（幂等锁 + 任务级锁）
    orphan_removed = _cleanup_orphan_task_locks()

    logger.info(
        "[cleanup] 完成：删除研究任务 %d 条，清理 Redis 孤儿锁 %d 个",
        deleted_count,
        orphan_removed,
    )
    return {"deleted_tasks": deleted_count, "orphan_lock_keys_removed": orphan_removed}


async def _delete_old_tasks(cutoff: datetime) -> int:
    """异步执行 DB 删除，返回删除行数。"""
    async with async_session_factory() as session:
        result = await session.execute(
            sa_delete(ResearchTask).where(
                ResearchTask.completed_at.isnot(None),
                ResearchTask.completed_at < cutoff,
            )
        )
        await session.commit()
        return result.rowcount


@celery_app.task(name="app.tasks.periodic.cleanup_stale_refresh_tokens", bind=True, max_retries=3)
def cleanup_stale_refresh_tokens(self, max_age_days: int | None = None) -> dict:
    """清理已过期或已吊销超过 max_age_days 天的刷新令牌。

    Args:
        max_age_days: 令牌保留天数，默认读取 CLEANUP_REFRESH_TOKEN_MAX_AGE_DAYS 或 90

    Returns:
        {"deleted_tokens": int}
    """
    if max_age_days is None:
        max_age_days = getattr(settings, "CLEANUP_REFRESH_TOKEN_MAX_AGE_DAYS", 90)

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    logger.info("[cleanup] 开始清理 %s 前的过期/吊销刷新令牌", cutoff.isoformat())

    try:
        import asyncio

        deleted_count = asyncio.run(_delete_stale_tokens(cutoff))
    except Exception as exc:
        logger.exception("[cleanup] 清理过期刷新令牌失败")
        raise self.retry(exc=exc, countdown=60) from exc

    logger.info("[cleanup] 完成：删除刷新令牌 %d 条", deleted_count)
    return {"deleted_tokens": deleted_count}


async def _delete_stale_tokens(cutoff: datetime) -> int:
    """异步删除过期或吊销时间超过阈值的刷新令牌。"""
    async with async_session_factory() as session:
        result = await session.execute(
            sa_delete(RefreshToken).where(
                sa.or_(
                    RefreshToken.expires_at < datetime.now(timezone.utc),
                    sa.and_(
                        RefreshToken.revoked_at.isnot(None),
                        RefreshToken.revoked_at < cutoff,
                    ),
                )
            )
        )
        await session.commit()
        return result.rowcount


def _cleanup_orphan_task_locks() -> int:
    """扫描 Redis 中任务相关锁，删除对应任务已不存在的孤儿 Key。

    仅处理任务级锁（rm:task_lock:{task_id}）和 Step 幂等锁（rm:idempotency:{task_id}:*），
    通过异步 DB 批量存在性检查避免 N+1 查询。
    """
    redis_client = get_redis()
    removed = 0

    try:
        # 收集所有可能的任务 ID
        task_ids_from_locks: set[str] = set()
        lock_keys: list[str] = []

        for pattern in [f"{TASK_LOCK_PREFIX}:*", f"{KEY_PREFIX}:*"]:
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
                for key in keys:
                    key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                    task_id = _extract_task_id_from_lock_key(key_str)
                    if task_id:
                        task_ids_from_locks.add(task_id)
                        lock_keys.append(key_str)
                if cursor == 0:
                    break

        if not task_ids_from_locks:
            return 0

        # 批量检查 DB 存在性
        existing_task_ids = _check_tasks_exist(task_ids_from_locks)

        # 删除不存在任务的锁
        for key in lock_keys:
            task_id = _extract_task_id_from_lock_key(key)
            if task_id and task_id not in existing_task_ids:
                redis_client.delete(key)
                removed += 1
                logger.debug("[cleanup] 删除孤儿锁: %s", key)

    except Exception:
        logger.exception("[cleanup] 清理 Redis 孤儿锁失败，继续执行")
        # 锁清理是兜底，不阻塞主流程

    return removed


def _extract_task_id_from_lock_key(key: str) -> str | None:
    """从 Redis 锁 Key 中提取任务 ID。

    支持格式：
    - rm:task_lock:{task_id}
    - rm:idempotency:{task_id}:{step_type}
    """
    parts = key.split(":")
    if len(parts) >= 3 and parts[0] == "rm":
        if parts[1] == "task_lock" and len(parts) == 3:
            return parts[2]
        if parts[1] == "idempotency" and len(parts) >= 3:
            return parts[2]
    return None


def _check_tasks_exist(task_ids: set[str]) -> set[str]:
    """异步批量检查任务是否存在，返回存在的任务 ID 集合。"""
    import asyncio

    return asyncio.run(_check_tasks_exist_async(task_ids))


async def _check_tasks_exist_async(task_ids: set[str]) -> set[str]:
    """异步批量检查任务是否存在。"""
    if not task_ids:
        return set()

    async with async_session_factory() as session:
        result = await session.execute(
            sa_select(ResearchTask.id).where(ResearchTask.id.in_(task_ids))
        )
        return {row[0] for row in result.all()}
