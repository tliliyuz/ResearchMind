"""AgentLoop 单元测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.context import AgentContext
from app.agent.exceptions import AgentLoopExhaustedError
from app.agent.loop import AgentLoop
from app.agent.memory import WorkingMemory
from app.agent.state import PhaseController
from app.core.llm import LLMResult, ToolCall
from app.pipeline.sse_bridge import (
    EVENT_AGENT_ACTION,
    EVENT_AGENT_OBSERVATION,
    EVENT_AGENT_THOUGHT,
    SSEBridge,
)
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.registry import ToolRegistry


class DummyTool(Tool):
    def __init__(self, name: str, mapped_phase: str | None):
        self.name = name
        self.description = f"tool {name}"
        self.parameters_schema = {"type": "object", "properties": {}}
        self.mapped_phase = mapped_phase

    async def execute(self, ctx, **params):
        return ToolResult(success=True, output={"ok": True}, observation=f"obs {self.name}")


@pytest.fixture
def setup():
    reg = ToolRegistry()
    reg.register(DummyTool("plan_tool", "planning"))
    reg.register(DummyTool("search_tool", "search"))
    ctx = AgentContext(current_phase="planning")
    memory = WorkingMemory()
    sse = MagicMock(spec=SSEBridge)
    sse.publish = AsyncMock()
    controller = PhaseController(ctx, reg)
    loop = AgentLoop(controller, memory, sse, max_iterations=10)
    tool_ctx = MagicMock(spec=ToolContext)
    tool_ctx.agent_context = ctx
    return loop, tool_ctx, sse, reg, ctx


def _make_llm_result(tool_calls=None, reasoning="", content=""):
    return LLMResult(
        content=content,
        reasoning_content=reasoning,
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        tool_calls=tool_calls,
    )


def _callback_factory(agent_ctx):
    async def callback(tool, tool_call):
        if tool.name == "finish_tool":
            agent_ctx.finished = True
            return ToolResult(success=True, output={}, observation="finished")
        return ToolResult(success=True, output={"ok": True}, observation=f"obs {tool.name}")
    return callback


class TestAgentLoop:
    async def test_finish_tool_结束循环(self, setup, monkeypatch):
        loop, tool_ctx, sse, reg, agent_ctx = setup

        async def fake_chat(*args, **kwargs):
            return _make_llm_result(
                reasoning="完成",
                tool_calls=[ToolCall(id="1", name="finish_tool", arguments={})],
            )

        monkeypatch.setattr("app.agent.loop.chat_completion", fake_chat)

        await loop.run(tool_ctx, _callback_factory(agent_ctx))

        assert agent_ctx.finished is True
        sse.publish.assert_any_call(EVENT_AGENT_THOUGHT, {"iteration": 1, "phase": "planning", "thought": "完成"})
        sse.publish.assert_any_call(EVENT_AGENT_ACTION, {"iteration": 1, "phase": "planning", "tool_call_id": "1", "tool_name": "finish_tool", "arguments": {}})
        sse.publish.assert_any_call(EVENT_AGENT_OBSERVATION, {"iteration": 1, "phase": "planning", "tool_call_id": "1", "tool_name": "finish_tool", "observation": "finished", "success": True})

    async def test_非法tool返回失败observation(self, setup, monkeypatch):
        loop, tool_ctx, sse, reg, agent_ctx = setup

        responses = [
            _make_llm_result(tool_calls=[ToolCall(id="1", name="render_tool", arguments={})]),
            _make_llm_result(tool_calls=[ToolCall(id="2", name="finish_tool", arguments={})]),
        ]
        iter_resp = iter(responses)

        async def fake_chat(*args, **kwargs):
            return next(iter_resp)

        monkeypatch.setattr("app.agent.loop.chat_completion", fake_chat)
        callback = AsyncMock()

        await loop.run(tool_ctx, _callback_factory(agent_ctx))

        # render_tool 不在 planning phase，callback 不应被非法 tool 调用
        for call in callback.await_args_list:
            assert call.args[0].name != "render_tool"
        obs_call = [c for c in sse.publish.await_args_list if c.args[0] == EVENT_AGENT_OBSERVATION]
        assert obs_call
        assert "不可用" in obs_call[0].args[1]["observation"]

    async def test_达到最大迭代次数抛出异常(self, setup, monkeypatch):
        loop, tool_ctx, sse, reg, agent_ctx = setup
        loop._max_iterations = 2

        async def fake_chat(*args, **kwargs):
            return _make_llm_result(tool_calls=[ToolCall(id="1", name="plan_tool", arguments={})])

        monkeypatch.setattr("app.agent.loop.chat_completion", fake_chat)
        callback = AsyncMock(return_value=ToolResult(success=True, output={"ok": True}, observation="ok"))

        with pytest.raises(AgentLoopExhaustedError):
            await loop.run(tool_ctx, callback)

    async def test_primary_tool成功后推进phase(self, setup, monkeypatch):
        loop, tool_ctx, sse, reg, agent_ctx = setup

        responses = [
            _make_llm_result(tool_calls=[ToolCall(id="1", name="plan_tool", arguments={})]),
            _make_llm_result(tool_calls=[ToolCall(id="2", name="search_tool", arguments={})]),
            _make_llm_result(tool_calls=[ToolCall(id="3", name="finish_tool", arguments={})]),
        ]
        iter_resp = iter(responses)

        async def fake_chat(*args, **kwargs):
            return next(iter_resp)

        monkeypatch.setattr("app.agent.loop.chat_completion", fake_chat)

        await loop.run(tool_ctx, _callback_factory(agent_ctx))

        assert agent_ctx.finished is True
        assert "planning" in agent_ctx.completed_phases
        assert "search" in agent_ctx.completed_phases
