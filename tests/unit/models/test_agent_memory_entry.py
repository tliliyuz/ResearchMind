"""AgentMemoryEntry 模型单元测试。"""

import pytest
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_memory_entry import AgentMemoryEntry
from app.models.enums import MEMORY_ENTRY_TYPE_ENUM
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.user import User


class TestAgentMemoryEntryModel:
    async def test_字段默认值与FK(self, db_session: AsyncSession, seeded_user):
        user, _ = seeded_user
        task = ResearchTask(
            id="mem-task-1",
            user_id=user.id,
            topic="test",
            requirements={},
            status="running",
        )
        db_session.add(task)
        await db_session.flush()

        step = ResearchStep(id="mem-step-1", task_id=task.id, step_type="planning", status="running")
        db_session.add(step)
        await db_session.flush()

        entry = AgentMemoryEntry(
            task_id=task.id,
            step_id=step.id,
            iteration=1,
            phase="planning",
            entry_type="thought",
            content={"thought": "hello"},
        )
        db_session.add(entry)
        await db_session.flush()

        assert entry.id is not None
        assert entry.task_id == task.id
        assert entry.step_id == step.id
        assert entry.iteration == 1
        assert entry.phase == "planning"
        assert entry.entry_type == "thought"
        assert entry.content == {"thought": "hello"}
        assert entry.created_at is not None

    async def test_entry_type_ENUM定义(self, db_session: AsyncSession):
        from app.core.database import Base

        table = Base.metadata.tables["agent_memory_entries"]
        entry_type_col = table.c["entry_type"]
        assert entry_type_col.type.name == "agent_memory_entry_type"
        assert set(entry_type_col.type.enums) == set(MEMORY_ENTRY_TYPE_ENUM)

    async def test_step_id可空(self, db_session: AsyncSession, seeded_user):
        user, _ = seeded_user
        task = ResearchTask(
            id="mem-task-3",
            user_id=user.id,
            topic="test",
            requirements={},
            status="running",
        )
        db_session.add(task)
        await db_session.flush()

        entry = AgentMemoryEntry(
            task_id=task.id,
            step_id=None,
            iteration=1,
            phase="planning",
            entry_type="thought",
            content={},
        )
        db_session.add(entry)
        await db_session.flush()

        assert entry.step_id is None

    async def test_索引存在(self, db_session: AsyncSession):
        from app.core.database import Base

        table = Base.metadata.tables["agent_memory_entries"]
        index_names = {idx.name for idx in table.indexes}
        assert "idx_agent_memory_task" in index_names
        assert "idx_agent_memory_task_created" in index_names
        assert "idx_agent_memory_task_iteration" in index_names
