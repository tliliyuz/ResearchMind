"""finish_tool 单元测试。"""

from unittest.mock import MagicMock

import pytest

from app.agent.context import AgentContext
from app.agent.memory import WorkingMemory
from app.tools.base import ToolContext
from app.tools.finish_tool import FinishTool


@pytest.fixture
def tool_context():
    task = MagicMock()
    step = MagicMock()
    session = MagicMock()
    sse = MagicMock()
    trace = MagicMock()
    agent_ctx = AgentContext(current_phase="render")
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


class TestFinishTool:
    async def test_默认reason结束(self, tool_context):
        tool = FinishTool()
        result = await tool.execute(tool_context)

        assert result.success is True
        assert tool_context.agent_context.finished is True
        assert tool_context.agent_context.finish_reason == "finished_by_llm"
        assert result.output["finished"] is True

    async def test_自定义reason结束(self, tool_context):
        tool = FinishTool()
        result = await tool.execute(tool_context, reason="all phases completed")

        assert tool_context.agent_context.finished is True
        assert tool_context.agent_context.finish_reason == "all phases completed"
        assert result.observation == "Agent 已显式结束运行"
