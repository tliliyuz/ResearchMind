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
    async def test_write_返回包含memory_note的output(self, tool_context):
        tool = MemoryTool()
        result = await tool.execute(tool_context, operation="write", content="note A")

        assert result.success is True
        # Phase 3 修正：memory_tool 不再自行写入 WorkingMemory，条目由 AgentLoop 统一记录
        assert tool_context.working_memory.recent() == []
        assert result.output["operation"] == "write"
        assert result.output["memory_note"] == "note A"
        assert result.output["entries_count"] == 0

    async def test_append_与write等价追加(self, tool_context):
        tool = MemoryTool()
        result_a = await tool.execute(tool_context, operation="write", content="note A")
        result_b = await tool.execute(tool_context, operation="append", content="note B")

        assert result_a.success is True
        assert result_b.success is True
        assert result_a.output["memory_note"] == "note A"
        assert result_b.output["memory_note"] == "note B"
        assert tool_context.working_memory.recent() == []

    async def test_read_返回最近条目摘要(self, tool_context):
        tool = MemoryTool()
        tool_context.working_memory.add(ReActEntry(
            iteration=1, phase="planning", tool_name="plan_tool", observation="plan done",
        ))
        tool_context.working_memory.add(ReActEntry(
            iteration=2, phase="search", tool_name="search_tool", observation="search done",
        ))

        result = await tool.execute(tool_context, operation="read", limit=1)

        assert result.success is True
        assert result.output["entries_count"] == 1
        assert "最近 1 条" in result.observation
        assert "最近 phase=search" in result.observation
        assert "plan done" not in result.observation

    async def test_read_默认limit5(self, tool_context):
        tool = MemoryTool()
        for i in range(6):
            tool_context.working_memory.add(ReActEntry(
                iteration=i + 1, phase="search", tool_name="search_tool",
            ))

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
