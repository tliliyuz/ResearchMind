"""Celery Step 幂等锁单元测试 — 覆盖 acquire_step_lock / release_step_lock / check_step_lock / 异步版

对齐 ROADMAP.md §3.9：
  - Redis SET NX 获取锁
  - 已存在拒绝
  - TTL 过期后重新获取
  - 阶段完成后释放
  - 异步版 acquire/release/check

Mock Redis 客户端（在函数边界截断），验证锁 Key 格式、NX/EX 参数传递。
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.tasks.lock import (
    _build_lock_key,
    acquire_step_lock,
    release_step_lock,
    check_step_lock,
    acquire_step_lock_async,
    release_step_lock_async,
    KEY_PREFIX,
)


# ═══════════════════════════════════════════════════════════════
# Key 格式
# ═══════════════════════════════════════════════════════════════


def test_build_lock_key_格式为_prefix_task_id_step_type():
    """锁 Key 格式：`rm:idempotency:{task_id}:{step_type}`"""
    key = _build_lock_key("abc-123", "planning")
    assert key == f"{KEY_PREFIX}:abc-123:planning"


def test_build_lock_key_包含连字符的UUID():
    key = _build_lock_key("550e8400-e29b-41d4-a716-446655440000", "search")
    assert key == f"{KEY_PREFIX}:550e8400-e29b-41d4-a716-446655440000:search"


# ═══════════════════════════════════════════════════════════════
# acquire_step_lock（同步版）
# ═══════════════════════════════════════════════════════════════


@patch("app.tasks.lock.get_redis")
def test_acquire_step_lock_获取成功_返回True(mock_get_redis):
    """Redis SET NX 成功（返回非空）→ acquire 返回 True"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_get_redis.return_value = mock_redis

    result = acquire_step_lock("task-1", "planning")
    assert result is True

    mock_redis.set.assert_called_once()
    args, kwargs = mock_redis.set.call_args
    assert args[0] == f"{KEY_PREFIX}:task-1:planning"
    assert args[1] == "locked"
    assert kwargs["ex"] == 600
    assert kwargs["nx"] is True


@patch("app.tasks.lock.get_redis")
def test_acquire_step_lock_锁已存在_返回False(mock_get_redis):
    """Redis SET NX 失败（返回 None → bool(None)=False）→ acquire 返回 False"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = None
    mock_get_redis.return_value = mock_redis

    result = acquire_step_lock("task-1", "planning")
    assert result is False


@patch("app.tasks.lock.get_redis")
def test_acquire_step_lock_自定义TTL(mock_get_redis):
    """自定义 TTL 覆盖默认值 600s"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_get_redis.return_value = mock_redis

    acquire_step_lock("task-2", "fetch", ttl=60)
    kwargs = mock_redis.set.call_args[1]
    assert kwargs["ex"] == 60


@patch("app.tasks.lock.get_redis")
def test_acquire_step_lock_不同step_type使用不同key(mock_get_redis):
    """planning 与 search 的锁 Key 不同"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_get_redis.return_value = mock_redis

    acquire_step_lock("task-1", "planning")
    acquire_step_lock("task-1", "search")

    assert mock_redis.set.call_count == 2
    call_args_0 = mock_redis.set.call_args_list[0][0][0]
    call_args_1 = mock_redis.set.call_args_list[1][0][0]
    assert "planning" in call_args_0
    assert "search" in call_args_1
    assert call_args_0 != call_args_1


@patch("app.tasks.lock.get_redis")
def test_acquire_step_lock_不同task_id使用不同key(mock_get_redis):
    """不同 task_id 的锁 Key 不同"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_get_redis.return_value = mock_redis

    acquire_step_lock("task-a", "planning")
    acquire_step_lock("task-b", "planning")

    call_args_0 = mock_redis.set.call_args_list[0][0][0]
    call_args_1 = mock_redis.set.call_args_list[1][0][0]
    assert "task-a" in call_args_0
    assert "task-b" in call_args_1
    assert call_args_0 != call_args_1


@patch("app.tasks.lock.get_redis")
def test_acquire_step_lock_七阶段全类型可获取(mock_get_redis):
    """所有 7 种 step_type 都能正常构建 Key 并尝试获取"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_get_redis.return_value = mock_redis

    phases = ["planning", "search", "fetch", "rerank", "synthesis", "evidence_graph", "render"]
    for p in phases:
        result = acquire_step_lock("task-1", p)
        assert result is True

    assert mock_redis.set.call_count == 7


# ═══════════════════════════════════════════════════════════════
# release_step_lock
# ═══════════════════════════════════════════════════════════════


@patch("app.tasks.lock.get_redis")
def test_release_step_lock_删除对应key(mock_get_redis):
    """释放锁 → Redis DELETE 对应 Key"""
    mock_redis = MagicMock()
    mock_get_redis.return_value = mock_redis

    release_step_lock("task-1", "planning")
    mock_redis.delete.assert_called_once_with(
        f"{KEY_PREFIX}:task-1:planning"
    )


@patch("app.tasks.lock.get_redis")
def test_release_step_lock_重复释放不报错(mock_get_redis):
    """重复释放锁 → 幂等操作，不抛异常"""
    mock_redis = MagicMock()
    mock_get_redis.return_value = mock_redis

    release_step_lock("task-1", "planning")
    release_step_lock("task-1", "planning")
    assert mock_redis.delete.call_count == 2


@patch("app.tasks.lock.get_redis")
def test_release_step_lock_释放后锁不存在(mock_get_redis):
    """释放后 check_step_lock → False"""
    mock_redis = MagicMock()
    mock_redis.exists.return_value = 0
    mock_get_redis.return_value = mock_redis

    release_step_lock("task-1", "planning")
    assert check_step_lock("task-1", "planning") is False


# ═══════════════════════════════════════════════════════════════
# check_step_lock
# ═══════════════════════════════════════════════════════════════


@patch("app.tasks.lock.get_redis")
def test_check_step_lock_锁存在_返回True(mock_get_redis):
    """Redis EXISTS > 0 → 锁存在"""
    mock_redis = MagicMock()
    mock_redis.exists.return_value = 1
    mock_get_redis.return_value = mock_redis

    assert check_step_lock("task-1", "planning") is True
    mock_redis.exists.assert_called_once_with(
        f"{KEY_PREFIX}:task-1:planning"
    )


@patch("app.tasks.lock.get_redis")
def test_check_step_lock_锁不存在_返回False(mock_get_redis):
    """Redis EXISTS == 0 → 锁不存在"""
    mock_redis = MagicMock()
    mock_redis.exists.return_value = 0
    mock_get_redis.return_value = mock_redis

    assert check_step_lock("task-1", "planning") is False


# ═══════════════════════════════════════════════════════════════
# 完整生命周期
# ═══════════════════════════════════════════════════════════════


@patch("app.tasks.lock.get_redis")
def test_完整生命周期_获取执行释放(mock_get_redis):
    """获取锁→执行→释放锁→释放后锁不存在"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.exists.return_value = 0
    mock_get_redis.return_value = mock_redis

    # 获取
    assert acquire_step_lock("task-1", "planning") is True
    # 执行（用 check 验证仍在锁定）
    mock_redis.exists.return_value = 1
    assert check_step_lock("task-1", "planning") is True
    # 释放
    release_step_lock("task-1", "planning")
    # 释放后
    mock_redis.exists.return_value = 0
    assert check_step_lock("task-1", "planning") is False


@patch("app.tasks.lock.get_redis")
def test_并发获取_第二个请求被拒绝(mock_get_redis):
    """模拟并发：第 1 个获取成功，第 2 个被拒绝"""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_get_redis.return_value = mock_redis

    assert acquire_step_lock("task-1", "planning") is True

    mock_redis.set.return_value = None
    assert acquire_step_lock("task-1", "planning") is False


# ═══════════════════════════════════════════════════════════════
# 异步版
# ═══════════════════════════════════════════════════════════════


def _make_async_mock_set(return_value):
    """构造一个 awaitable mock：set 方法返回 coroutine"""
    async def _set(*args, **kwargs):
        return return_value
    return _set


def _make_async_mock_delete():
    async def _delete(*args, **kwargs):
        return None
    return _delete


@pytest.mark.asyncio
async def test_acquire_step_lock_async_获取成功_返回True():
    """异步版：Redis SET NX 成功 → True"""
    with patch("app.core.redis_client.get_async_redis") as mock_get_async:
        mock_redis = MagicMock()
        mock_redis.set = _make_async_mock_set(True)
        mock_get_async.return_value = mock_redis

        result = await acquire_step_lock_async("task-1", "planning")
        assert result is True


@pytest.mark.asyncio
async def test_acquire_step_lock_async_锁已存在_返回False():
    """异步版：Redis SET NX 失败 → False"""
    with patch("app.core.redis_client.get_async_redis") as mock_get_async:
        mock_redis = MagicMock()
        mock_redis.set = _make_async_mock_set(None)
        mock_get_async.return_value = mock_redis

        result = await acquire_step_lock_async("task-1", "planning")
        assert result is False


@pytest.mark.asyncio
async def test_release_step_lock_async_删除对应key():
    """异步版：释放锁 → DELETE Key"""
    with patch("app.core.redis_client.get_async_redis") as mock_get_async:
        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock(return_value=None)
        mock_get_async.return_value = mock_redis

        await release_step_lock_async("task-1", "search")

        mock_redis.delete.assert_called_once_with(f"{KEY_PREFIX}:task-1:search")


@pytest.mark.asyncio
async def test_acquire_step_lock_async_自定义TTL():
    """异步版：自定义 TTL"""
    import asyncio

    with patch("app.core.redis_client.get_async_redis") as mock_get_async:
        captured_kwargs = {}

        async def _capture_set(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return True

        mock_redis = MagicMock()
        mock_redis.set = _capture_set
        mock_get_async.return_value = mock_redis

        await acquire_step_lock_async("task-2", "fetch", ttl=120)
        assert captured_kwargs["ex"] == 120
