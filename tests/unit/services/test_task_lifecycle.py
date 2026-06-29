"""task_lifecycle 共享原语单元测试。"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import STEP_TYPE_ENUM
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.services.task_lifecycle import (
    TaskLockHandle,
    emergency_fail_task,
    load_task_steps,
    start_research_task,
)


@pytest.fixture
def fake_locks(monkeypatch):
    """Mock Redis 任务锁函数，避免测试依赖 Redis。"""
    lock_state = {"locked": False}

    async def acquire(task_id, ttl=None):
        if not lock_state["locked"]:
            lock_state["locked"] = True
            return True
        return False

    async def release(task_id):
        lock_state["locked"] = False

    async def refresh(task_id, ttl=None):
        return lock_state["locked"]

    monkeypatch.setattr("app.services.task_lifecycle.acquire_task_lock_async", acquire)
    monkeypatch.setattr("app.services.task_lifecycle.release_task_lock_async", release)
    monkeypatch.setattr("app.services.task_lifecycle.refresh_task_lock_async", refresh)
    return lock_state


class TestTaskLockHandle:
    async def test_acquire_release(self, fake_locks):
        handle = TaskLockHandle("task-1")
        assert await handle.acquire() is True
        assert handle.acquired is True
        await handle.release()
        assert handle.acquired is False
        assert fake_locks["locked"] is False


class TestStartResearchTask:
    async def test_pending任务启动(self, db_session: AsyncSession, seeded_user, fake_locks, monkeypatch):
        user, _ = seeded_user
        task = ResearchTask(
            id="task-1",
            user_id=user.id,
            topic="test",
            requirements={},
            status="pending",
            total_steps=0,
        )
        db_session.add(task)
        await db_session.flush()

        # 单元测试中避免真实 commit 破坏事务隔离：将 commit 重定向为 flush
        monkeypatch.setattr(db_session, "commit", db_session.flush)

        sse = AsyncMock()
        handle = TaskLockHandle("task-1")
        try:
            started = await start_research_task(task, db_session, sse, handle)

            assert started is True
            assert task.status == "running"
            assert task.total_steps == len(STEP_TYPE_ENUM)
            sse.publish.assert_awaited_once()
        finally:
            await handle.release()

    async def test_终态任务不启动(self, db_session: AsyncSession, seeded_user, fake_locks):
        user, _ = seeded_user
        task = ResearchTask(
            id="task-2",
            user_id=user.id,
            topic="test",
            requirements={},
            status="completed",
        )
        db_session.add(task)
        await db_session.flush()

        sse = AsyncMock()
        handle = TaskLockHandle("task-2")
        started = await start_research_task(task, db_session, sse, handle)

        assert started is False


class TestLoadTaskSteps:
    async def test_加载任务steps(self, db_session: AsyncSession, seeded_user):
        user, _ = seeded_user
        task = ResearchTask(
            id="task-3", user_id=user.id, topic="t", requirements={}, status="running"
        )
        db_session.add(task)
        await db_session.flush()

        step1 = ResearchStep(task_id="task-3", step_type="planning", status="completed")
        step2 = ResearchStep(task_id="task-3", step_type="search", status="running")
        db_session.add_all([step1, step2])
        await db_session.flush()

        steps = await load_task_steps(db_session, "task-3")
        assert len(steps) == 2
        assert {s.step_type for s in steps} == {"planning", "search"}


class TestEmergencyFailTask:
    async def test_running任务被标记为failed(self, db_session: AsyncSession, seeded_user):
        user, _ = seeded_user
        task = ResearchTask(
            id="task-4", user_id=user.id, topic="t", requirements={}, status="running"
        )
        db_session.add(task)
        await db_session.flush()

        updated = await emergency_fail_task(db_session, "task-4", "E3999", "test error")
        assert updated is True
        await db_session.refresh(task)
        assert task.status == "failed"
        assert task.error_code == "E3999"

    async def test_completed任务不覆盖(self, db_session: AsyncSession, seeded_user):
        user, _ = seeded_user
        task = ResearchTask(
            id="task-5", user_id=user.id, topic="t", requirements={}, status="completed"
        )
        db_session.add(task)
        await db_session.flush()

        updated = await emergency_fail_task(db_session, "task-5")
        assert updated is False
