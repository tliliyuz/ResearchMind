"""SSE 端点测试 — stream 连接、状态快照、心跳格式。"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep


async def _seed_task_for_sse(db_session) -> ResearchTask:
    """创建测试用 ResearchTask + 已完成的 Planning step。"""
    from app.models.user import User
    from app.core.security import hash_password

    # 确保用户存在
    existing_user = await db_session.get(User, 1)
    if existing_user is None:
        user = User(
            id=1, username="testuser",
            password_hash=hash_password("testpass123"),
            role="user", status="active",
        )
        db_session.add(user)
        await db_session.flush()

    task = ResearchTask(
        id="sse-task-uuid-001",
        user_id=1,
        topic="SSE测试主题",
        requirements={"task_type": "analysis", "max_sources": 10, "language": "zh"},
        status="running",
        current_phase="searching",
        total_steps=3,
        completed_steps=1,
        total_sources=3,
        total_evidence=0,
    )
    db_session.add(task)
    await db_session.flush()

    # 添加一个 completed planning step
    step = ResearchStep(
        id="sse-step-uuid-001",
        task_id=task.id,
        step_type="planning",
        status="completed",
        label="Planning：拆解研究主题",
        output={"sub_questions": ["q1", "q2", "q3"], "rationale": "test"},
        duration_ms=1500,
    )
    db_session.add(step)
    await db_session.flush()

    return task


class TestSSEStateEndpoint:
    """GET /api/research/{task_id}/state — REST 状态快照。"""

    @pytest.mark.asyncio
    async def test_正常返回状态快照(self, async_client: AsyncClient, auth_headers: dict, db_session):
        await _seed_task_for_sse(db_session)

        response = await async_client.get(
            "/api/research/sse-task-uuid-001/state",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "0"

        snapshot = data["data"]
        assert snapshot["task_id"] == "sse-task-uuid-001"
        assert snapshot["status"] == "running"
        assert snapshot["current_phase"] == "searching"
        assert snapshot["progress"]["completed_steps"] == 1
        assert snapshot["progress"]["total_steps"] == 3
        assert len(snapshot["steps"]) >= 1
        # 验证 planning step 在步骤列表中
        planning_steps = [s for s in snapshot["steps"] if s["step_type"] == "planning"]
        assert len(planning_steps) == 1
        assert planning_steps[0]["status"] == "completed"
        # 字段名应为 id（与 API.md §3.6 对齐）
        assert "id" in planning_steps[0]
        assert planning_steps[0]["id"] == "sse-step-uuid-001"

    @pytest.mark.asyncio
    async def test_任务不存在_返回404(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.get(
            "/api/research/non-existent-uuid/state",
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "E2001"

    @pytest.mark.asyncio
    async def test_无权访问_返回403(self, async_client: AsyncClient, auth_headers: dict, db_session):
        # 创建属于 user_id=2 的任务
        from app.models.user import User
        from app.core.security import hash_password

        existing = await db_session.get(User, 2)
        if existing is None:
            user2 = User(
                id=2, username="otheruser",
                password_hash=hash_password("testpass123"),
                role="user", status="active",
            )
            db_session.add(user2)
            await db_session.flush()

        task = ResearchTask(
            id="sse-task-uuid-other",
            user_id=2,  # 不属于当前用户
            topic="其他用户的任务",
            requirements={"task_type": "explainer", "max_sources": 5, "language": "zh"},
            status="running",
        )
        db_session.add(task)
        await db_session.flush()

        response = await async_client.get(
            "/api/research/sse-task-uuid-other/state",
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert response.json()["code"] == "E2002"

    @pytest.mark.asyncio
    async def test_未登录_返回401(self, async_client: AsyncClient):
        response = await async_client.get(
            "/api/research/sse-task-uuid-001/state",
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_失败任务含错误信息(self, async_client: AsyncClient, auth_headers: dict, db_session):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        task = await _seed_task_for_sse(db_session)
        task.status = "failed"
        task.error_code = "E3102"
        task.error_message = "Tavily API完全不可用"
        task.recoverable = True
        await db_session.flush()

        # 通过 eager-load 重新获取 task，确保关系已加载
        stmt = select(ResearchTask).where(ResearchTask.id == task.id).options(
            selectinload(ResearchTask.steps)
        )
        result = await db_session.execute(stmt)
        task_reloaded = result.scalar_one()
        # 更新已加载对象的状态以匹配修改
        task_reloaded.status = task.status
        task_reloaded.error_code = task.error_code
        task_reloaded.error_message = task.error_message
        task_reloaded.recoverable = task.recoverable
        await db_session.flush()

        response = await async_client.get(
            "/api/research/sse-task-uuid-001/state",
            headers=auth_headers,
        )
        assert response.status_code == 200
        snapshot = response.json()["data"]
        assert snapshot["status"] == "failed"
        assert snapshot["error"]["error_code"] == "E3102"
        assert snapshot["error"]["recoverable"] is True


class TestSSEStreamEndpoint:
    """GET /api/research/{task_id}/stream — SSE 事件流。"""

    @pytest.mark.asyncio
    async def test_SSE连接成功_返回text_event_stream(self, async_client: AsyncClient, auth_headers: dict, db_session):
        """SSE 流连接验证 → 需要 Redis Pub/Sub，单元测试环境跳过。

        此测试需真实 Redis 运行，将在 tests/integration/ 中覆盖（Phase4）。
        """
        pytest.skip("SSE 流连接需要 Redis Pub/Sub，单元测试环境下跳过")

    @pytest.mark.asyncio
    async def test_stream端点权限校验_未登录返回401(self, async_client: AsyncClient):
        response = await async_client.get(
            "/api/research/sse-task-uuid-001/stream",
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_终态任务SSE只推送snapshot后关闭(self, async_client: AsyncClient, auth_headers: dict, db_session):
        task = await _seed_task_for_sse(db_session)
        task.status = "completed"
        await db_session.flush()

        response = await async_client.get(
            "/api/research/sse-task-uuid-001/stream",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        body = response.text
        assert "event: task.status.snapshot" in body
        # 终态任务不应进入 Redis 订阅循环，响应体应只包含 snapshot 事件
        assert body.count("event:") == 1


class TestSseSnapshotStructure:
    """快照数据结构完整性与进度校验。"""

    @pytest.mark.asyncio
    async def test_快照包含所有必要字段(self, async_client: AsyncClient, auth_headers: dict, db_session):
        await _seed_task_for_sse(db_session)

        response = await async_client.get(
            "/api/research/sse-task-uuid-001/state",
            headers=auth_headers,
        )
        snapshot = response.json()["data"]

        # 必需字段
        assert "task_id" in snapshot
        assert "status" in snapshot
        assert "current_phase" in snapshot
        assert "progress" in snapshot
        assert "steps" in snapshot
        assert "topics" in snapshot
        assert "created_at" in snapshot
        assert "stats" in snapshot

        # progress 子字段
        progress = snapshot["progress"]
        assert "completed_steps" in progress
        assert "total_steps" in progress
        assert "progress" in progress
        assert progress["progress"] >= 0.0

        # stats 子字段
        stats = snapshot["stats"]
        assert "total_sources" in stats
        assert "total_evidence" in stats

    @pytest.mark.asyncio
    async def test_进度计算正确_通过API(self, async_client: AsyncClient, auth_headers: dict, db_session):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        task = await _seed_task_for_sse(db_session)
        task.total_steps = 10
        task.completed_steps = 4
        await db_session.flush()

        # 通过 selectinload 重新加载 task，避免 MissingGreenlet
        stmt = select(ResearchTask).where(ResearchTask.id == task.id).options(
            selectinload(ResearchTask.steps)
        )
        await db_session.execute(stmt)

        response = await async_client.get(
            "/api/research/sse-task-uuid-001/state",
            headers=auth_headers,
        )
        progress = response.json()["data"]["progress"]
        assert progress["completed_steps"] == 4
        assert progress["total_steps"] == 10
        assert progress["progress"] == 0.4
