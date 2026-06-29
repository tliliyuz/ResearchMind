"""Tool 抽象基类单元测试 —— 覆盖 PhaseHandlerTool 与参数校验。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.context import AgentContext
from app.agent.memory import WorkingMemory
from app.tools.base import (
    PhaseHandlerTool,
    ToolContext,
    ToolResult,
    validate_tool_params,
)


class TestValidateToolParams:
    """validate_tool_params 轻量校验"""

    def test_空schema_无错误(self):
        errors = validate_tool_params({"a": 1}, {})
        assert errors == []

    def test_必填参数缺失(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        }
        errors = validate_tool_params({}, schema)
        assert "缺少必填参数 'x'" in errors

    def test_类型错误(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "name": {"type": "string"},
                "flag": {"type": "boolean"},
                "meta": {"type": "object"},
                "items": {"type": "array"},
            },
        }
        params = {
            "count": "1",
            "ratio": "0.5",
            "name": 123,
            "flag": "true",
            "meta": "not-dict",
            "items": "not-list",
        }
        errors = validate_tool_params(params, schema)
        assert len(errors) == 6
        for field in ("count", "ratio", "name", "flag", "meta", "items"):
            assert any(field in e for e in errors)

    def test_整数不是布尔(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        # bool 是 int 子类，但应被视为非法 integer
        errors = validate_tool_params({"x": True}, schema)
        assert any("x" in e for e in errors)

    def test_未知字段不拒绝(self):
        schema = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": [],
        }
        errors = validate_tool_params({"x": 1, "y": "extra"}, schema)
        assert errors == []

    def test_合法可选参数通过(self):
        schema = {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": [],
        }
        errors = validate_tool_params({"reason": "focus"}, schema)
        assert errors == []


class TestPhaseHandlerTool:
    """PhaseHandlerTool 包装执行"""

    @pytest.fixture
    def tool_context(self):
        task = MagicMock()
        step = MagicMock()
        session = MagicMock()
        sse = MagicMock()
        trace = MagicMock()
        agent_ctx = AgentContext(current_phase="planning")
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

    async def test_成功执行(self, tool_context):
        handler = AsyncMock(return_value={"ok": True})
        tool = PhaseHandlerTool(
            name="plan_tool",
            description="plan",
            mapped_phase="planning",
            handler=handler,
        )

        result = await tool.execute(tool_context)

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.output == {"ok": True}
        handler.assert_awaited_once_with(
            tool_context.task,
            tool_context.step,
            tool_context.session,
            tool_context.sse_bridge,
        )

    async def test_handler异常_包装为失败(self, tool_context):
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        tool = PhaseHandlerTool(
            name="plan_tool",
            description="plan",
            mapped_phase="planning",
            handler=handler,
        )

        result = await tool.execute(tool_context)

        assert result.success is False
        assert "boom" in result.observation
        assert result.error_message == "boom"

    async def test_参数校验失败_不调用handler(self, tool_context):
        handler = AsyncMock(return_value={"ok": True})
        schema = {
            "type": "object",
            "properties": {"top_k": {"type": "integer"}},
            "required": [],
        }
        tool = PhaseHandlerTool(
            name="rerank_tool",
            description="rerank",
            mapped_phase="rerank",
            handler=handler,
            parameters_schema=schema,
        )

        result = await tool.execute(tool_context, top_k="not-int")

        assert result.success is False
        assert "参数校验失败" in result.observation
        assert "top_k" in result.observation
        handler.assert_not_awaited()

    async def test_合法可选参数_透传handler(self, tool_context):
        handler = AsyncMock(return_value={"ok": True})
        schema = {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": [],
        }
        tool = PhaseHandlerTool(
            name="plan_tool",
            description="plan",
            mapped_phase="planning",
            handler=handler,
            parameters_schema=schema,
        )

        result = await tool.execute(tool_context, reason="focus on sub-question 2")

        assert result.success is True
        handler.assert_awaited_once()
