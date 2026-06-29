"""memory_tool 单元测试。"""

from unittest.mock import MagicMock

import pytest

from app.agent.context import AgentContext
from app.agent.memory import ReActEntry, WorkingMemory
from app.tools.base import ToolContext
from app.tools.memory_tool import MemoryTool


@pytest.fixture
def tool_context():
    task = MagicMock()
    step = MagicMock()
    session = MagicMock()
    sse = MagicMock()
    trace = MagicMock()
    agent_ctx = AgentContext(current_phase="search", iteration_count=3, last_step_id="step-1")
    memory = WorkingMemory()
    return ToolContext(
        task=task,
        step=step,
        session=session,
        sse_bridge=sse,
        trace_recorder=trace,
        agent_context=agent_ctx,
        working_memory=memory,
    )


class TestMemoryTool:
    async def test_write_追加条目(self, tool_context):
        tool = MemoryTool()
        result = await tool.execute(tool_context, operation="write", content="note A")

        assert result.success is True
        entries = tool_context.working_memory.recent()
        assert len(entries) == 1
        assert entries[0].tool_output_summary["memory_note"] == "note A"
        assert entries[0].phase == "search"
        assert entries[0].iteration == 3

    async def test_append_与write等价追加(self, tool_context):
        tool = MemoryTool()
        await tool.execute(tool_context, operation="write", content="note A")
        result = await tool.execute(tool_context, operation="append", content="note B")

        assert result.success is True
        entries = tool_context.working_memory.recent()
        assert len(entries) == 2
        assert entries[-1].tool_output_summary["memory_note"] == "note B"

    async def test_read_返回最近条目摘要(self, tool_context):
        tool = MemoryTool()
        await tool.execute(tool_context, operation="write", content="note A")
        await tool.execute(tool_context, operation="write", content="note B")

        result = await tool.execute(tool_context, operation="read", limit=1)

        assert result.success is True
        assert result.output["entries_count"] == 1
        assert "note B" in result.observation
        assert "note A" not in result.observation

    async def test_read_默认limit5(self, tool_context):
        tool = MemoryTool()
        for i in range(6):
            await tool.execute(tool_context, operation="write", content=f"note {i}")

        result = await tool.execute(tool_context, operation="read")

        assert result.output["entries_count"] == 5

    async def test_read_limit非法_返回校验失败(self, tool_context):
        tool = MemoryTool()
        result = await tool.execute(tool_context, operation="read", limit="bad")

        assert result.success is False
        assert "limit" in result.observation

    async def test_summary_返回统计(self, tool_context):
        tool = MemoryTool()
        tool_context.working_memory.add(ReActEntry(iteration=1, phase="planning", tool_name="plan_tool"))
        tool_context.working_memory.add(ReActEntry(iteration=2, phase="search", tool_name="search_tool"))

        result = await tool.execute(tool_context, operation="summary")

        assert result.success is True
        assert result.output["total_entries"] == 2
        assert result.output["latest_phase"] == "search"
        assert result.output["latest_tool"] == "search_tool"
        assert "共 2 条" in result.observation

    async def test_未知操作_返回未实现(self, tool_context):
        tool = MemoryTool()
        result = await tool.execute(tool_context, operation="query_long_term")

        assert result.success is False
        assert "Long Memory 在 Phase 2 未实现" in result.observation
