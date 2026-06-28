"""Celery research_task 单元测试 —— _emergency_fail CAS 与 recoverable 语义。"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select as sa_select

from app.core.exceptions import SearchFailedException
from app.models.research_task import ResearchTask
from app.models.user import User
from app.core.security import hash_password
from app.tasks.research_task import _emergency_fail


async def _seed_user_and_task(db_session, task_status: str = "pending") -> ResearchTask:
    """创建测试用户与任务。"""
    user = User(
        username="emergency-test-user",
        password_hash=hash_password("pass"),
        role="user",
        status="active",
    )
    db_session.add(user)
    await db_session.flush()

    task = ResearchTask(
        user_id=user.id,
        topic="emergency fail 测试",
        requirements={"task_type": "analysis", "max_sources": 10, "language": "zh"},
        status=task_status,
    )
    db_session.add(task)
    await db_session.flush()
    return task


class _SessionContextManager:
    """把已存在的 db_session 包装成 async_session_factory 的上下文管理器。

    重写 commit 为 flush，避免破坏测试事务隔离。
    """

    def __init__(self, session):
        self._session = session
        # 包装 commit 为 flush，避免 _emergency_fail 提交外层事务
        self._original_commit = session.commit
        session.commit = session.flush

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        self._session.commit = self._original_commit
        return False


def _emergency_fail_session_factory(db_session):
    """返回一个 session_factory，让 _emergency_fail 复用测试 db_session。"""
    def factory():
        return _SessionContextManager(db_session)
    return factory


class TestEmergencyFail:
    """_emergency_fail CAS 与 recoverable 语义测试。"""

    @pytest.mark.asyncio
    async def test_pending任务_CAS更新为failed(self, db_session):
        task = await _seed_user_and_task(db_session, "pending")

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=False)

        assert updated is True
        await db_session.refresh(task)
        assert task.status == "failed"
        assert task.error_code == "E3999"
        assert "模拟 Worker 崩溃" in task.error_message
        assert task.recoverable is False
        assert task.completed_at is not None

    @pytest.mark.asyncio
    async def test_running任务_CAS更新为failed(self, db_session):
        task = await _seed_user_and_task(db_session, "running")

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=True)

        assert updated is True
        await db_session.refresh(task)
        assert task.status == "failed"
        assert task.recoverable is True

    @pytest.mark.asyncio
    async def test_completed任务_不被覆盖(self, db_session):
        task = await _seed_user_and_task(db_session, "completed")
        task.completed_at = datetime.now(timezone.utc)
        original_message = task.error_message
        await db_session.flush()

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=False)

        assert updated is False
        await db_session.refresh(task)
        assert task.status == "completed"
        assert task.error_code is None
        assert task.error_message == original_message

    @pytest.mark.asyncio
    async def test_canceled任务_不被覆盖(self, db_session):
        task = await _seed_user_and_task(db_session, "canceled")
        task.completed_at = datetime.now(timezone.utc)
        await db_session.flush()

        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), "模拟 Worker 崩溃", recoverable=False)

        assert updated is False
        await db_session.refresh(task)
        assert task.status == "canceled"

    @pytest.mark.asyncio
    async def test_保留原异常recoverable语义(self, db_session):
        task = await _seed_user_and_task(db_session, "running")
        original_error = SearchFailedException("Tavily 不可用")

        recoverable = getattr(original_error, "error_detail", {}).get("recoverable", False)
        with patch(
            "app.tasks.research_task.async_session_factory",
            new=_emergency_fail_session_factory(db_session),
        ):
            updated = await _emergency_fail(str(task.id), str(original_error), recoverable=recoverable)

        assert updated is True
        await db_session.refresh(task)
        assert task.recoverable is True
