"""agent_memory_service 单元测试。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory import ReActEntry, WorkingMemory
from app.models.agent_memory_entry import AgentMemoryEntry
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.services import agent_memory_service


class TestClassifyReactEntry:
    def test_finish_tool返回finish(self):
        entry = ReActEntry(iteration=1, phase="render", tool_name="finish_tool")
        assert agent_memory_service.classify_react_entry(entry) == "finish"

    def test_有tool_name返回action(self):
        entry = ReActEntry(iteration=1, phase="search", tool_name="search_tool")
        assert agent_memory_service.classify_react_entry(entry) == "action"

    def test_无tool_name有observation返回observation(self):
        entry = ReActEntry(iteration=1, phase="search", observation="ok")
        assert agent_memory_service.classify_react_entry(entry) == "observation"

    def test_无tool_name无observation返回thought(self):
        entry = ReActEntry(iteration=1, phase="search", thought="思考")
        assert agent_memory_service.classify_react_entry(entry) == "thought"


class TestAgentMemoryService:
    async def _make_task(self, db_session: AsyncSession, seeded_user, task_id: str) -> ResearchTask:
        user, _ = seeded_user
        task = ResearchTask(
            id=task_id,
            user_id=user.id,
            topic="test",
            requirements={},
            status="running",
        )
        db_session.add(task)
        await db_session.flush()
        return task

    async def test_create_memory_entry_持久化单条(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-1")
        step = ResearchStep(id="svc-step-1", task_id=task.id, step_type="planning", status="running")
        db_session.add(step)
        await db_session.flush()

        entry = ReActEntry(
            iteration=1,
            phase="planning",
            thought="t",
            tool_name="plan_tool",
            observation="ok",
            step_id=step.id,
        )

        created = await agent_memory_service.create_memory_entry(db_session, task.id, entry)
        await db_session.flush()

        assert created.task_id == task.id
        assert created.entry_type == "action"
        assert created.iteration == 1
        assert created.phase == "planning"
        assert created.step_id == step.id
        assert created.content["thought"] == "t"

    async def test_list_memory_entries_默认按时间升序(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-2")
        for i in range(3):
            await agent_memory_service.create_memory_entry(
                db_session, task.id,
                ReActEntry(iteration=i + 1, phase="planning", thought=f"t{i}"),
            )
        await db_session.flush()

        rows = await agent_memory_service.list_memory_entries(db_session, task.id)
        assert len(rows) == 3
        assert [r.iteration for r in rows] == [1, 2, 3]

    async def test_list_memory_entries_按entry_type过滤(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-3")
        await agent_memory_service.create_memory_entry(
            db_session, task.id,
            ReActEntry(iteration=1, phase="planning", thought="t"),
        )
        await agent_memory_service.create_memory_entry(
            db_session, task.id,
            ReActEntry(iteration=1, phase="planning", tool_name="plan_tool", observation="ok"),
        )
        await db_session.flush()

        thoughts = await agent_memory_service.list_memory_entries(db_session, task.id, entry_type="thought")
        assert len(thoughts) == 1
        assert thoughts[0].entry_type == "thought"

    async def test_build_working_memory_时间线顺序(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-4")
        for i in range(3):
            await agent_memory_service.create_memory_entry(
                db_session, task.id,
                ReActEntry(iteration=i + 1, phase="planning", thought=f"t{i}"),
            )
        await db_session.flush()

        memory = await agent_memory_service.build_working_memory(db_session, task.id, max_entries=10)
        recent = memory.recent()
        assert len(recent) == 3
        assert [e.thought for e in recent] == ["t0", "t1", "t2"]

    async def test_build_working_memory_max_entries截断(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-5")
        for i in range(5):
            await agent_memory_service.create_memory_entry(
                db_session, task.id,
                ReActEntry(iteration=i + 1, phase="planning", thought=f"t{i}"),
            )
        await db_session.flush()

        memory = await agent_memory_service.build_working_memory(db_session, task.id, max_entries=2)
        recent = memory.recent()
        assert len(recent) == 2
        assert [e.thought for e in recent] == ["t3", "t4"]

    async def test_persist_pending_entries_批量持久化(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-6")
        memory = WorkingMemory(max_entries=10)
        memory.add(ReActEntry(iteration=1, phase="planning", thought="t1"))
        memory.add(ReActEntry(iteration=1, phase="planning", tool_name="plan_tool", observation="ok"))

        count = await agent_memory_service.persist_pending_entries(db_session, task.id, memory)
        await db_session.flush()

        assert count == 2
        assert memory.pending_entries() == []

        rows = await db_session.execute(
            sa_select(AgentMemoryEntry).where(AgentMemoryEntry.task_id == task.id)
        )
        assert len(rows.scalars().all()) == 2

    async def test_persist_pending_entries_空队列返回0(self, db_session: AsyncSession, seeded_user):
        task = await self._make_task(db_session, seeded_user, "svc-task-7")
        memory = WorkingMemory()
        count = await agent_memory_service.persist_pending_entries(db_session, task.id, memory)
        assert count == 0
