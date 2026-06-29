"""ToolRegistry 单元测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.base import PhaseHandlerTool, Tool
from app.tools.registry import ToolRegistry, build_default_tool_registry


class DummyTool(Tool):
    def __init__(self, name, mapped_phase=None):
        self.name = name
        self.description = f"tool {name}"
        self.parameters_schema = {"type": "object", "properties": {}}
        self.mapped_phase = mapped_phase

    async def execute(self, ctx, **params):
        return MagicMock()


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool("a_tool", "planning")
        reg.register(tool)
        assert reg.get("a_tool") is tool
        assert reg.get("nonexist") is None

    def test_list_tools_phase过滤(self):
        reg = ToolRegistry()
        reg.register(DummyTool("plan_tool", "planning"))
        reg.register(DummyTool("search_tool", "search"))
        names = {t.name for t in reg.list_tools("planning")}
        assert names == {"plan_tool"}

    def test_to_openai_schema_包含finish(self):
        reg = ToolRegistry()
        reg.register(DummyTool("plan_tool", "planning"))
        schemas = reg.to_openai_schema("planning")
        names = [s["function"]["name"] for s in schemas]
        assert "plan_tool" in names
        assert "finish_tool" in names

    def test_build_default_tool_registry_包含7个phase_tool(self):
        handlers = {phase: AsyncMock() for phase in ["planning", "search", "fetch", "rerank", "synthesis", "evidence_graph", "render"]}
        reg = build_default_tool_registry(handlers)
        expected_names = [
            "plan_tool", "search_tool", "fetch_tool", "rerank_tool",
            "synthesis_tool", "evidence_graph_tool", "render_tool",
        ]
        for name in expected_names:
            assert reg.get(name) is not None
        assert reg.get("finish_tool") is not None

    def test_build_default_tool_registry_缺失handler不注册(self):
        handlers = {"planning": AsyncMock()}
        reg = build_default_tool_registry(handlers)
        assert reg.get("plan_tool") is not None
        assert reg.get("search_tool") is None
