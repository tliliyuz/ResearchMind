"""AgentContext / PhaseController 单元测试。"""

from unittest.mock import MagicMock

import pytest

from app.agent.context import AgentContext
from app.agent.state import PhaseController
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class DummyTool(Tool):
    """测试用 Tool。"""

    def __init__(self, name: str, mapped_phase: str | None):
        self.name = name
        self.description = f"tool {name}"
        self.parameters_schema = {"type": "object", "properties": {}}
        self.mapped_phase = mapped_phase

    async def execute(self, ctx, **params):
        return MagicMock()


@pytest.fixture
def registry():
    reg = ToolRegistry()
    for phase in PhaseController.PHASE_ORDER:
        reg.register(DummyTool(f"{phase}_tool", phase))
    return reg


class TestAgentContext:
    def test_to_dict_序列化_completed_phases(self):
        ctx = AgentContext(
            current_phase="search",
            completed_phases={"planning"},
            iteration_count=3,
            last_step_id="step-1",
        )
        data = ctx.to_dict()
        assert data["current_phase"] == "search"
        assert data["completed_phases"] == ["planning"]
        assert data["iteration_count"] == 3
        assert data["last_step_id"] == "step-1"
        assert data["finished"] is False

    def test_from_dict_恢复状态(self):
        ctx = AgentContext.from_dict({
            "current_phase": "fetch",
            "completed_phases": ["planning", "search"],
            "iteration_count": 5,
            "last_step_id": "step-2",
            "finished": True,
            "finish_reason": "done",
        })
        assert ctx.current_phase == "fetch"
        assert ctx.completed_phases == {"planning", "search"}
        assert ctx.iteration_count == 5
        assert ctx.last_step_id == "step-2"
        assert ctx.finished is True
        assert ctx.finish_reason == "done"

    def test_from_dict_非法phase被过滤(self):
        ctx = AgentContext.from_dict({
            "completed_phases": ["planning", "invalid_phase"],
        })
        assert ctx.completed_phases == {"planning"}


class TestPhaseController:
    def test_初始current_phase为第一个未完成phase(self, registry):
        ctx = AgentContext(completed_phases={"planning"})
        ctrl = PhaseController(ctx, registry)
        assert ctrl.current_phase == "search"

    def test_get_available_tools_仅含当前phase和finish(self, registry):
        ctx = AgentContext(current_phase="fetch")
        ctrl = PhaseController(ctx, registry)
        names = {t.name for t in ctrl.get_available_tools()}
        assert "fetch_tool" in names
        assert "finish_tool" in names
        assert "plan_tool" not in names
        assert "search_tool" not in names

    def test_mark_phase_done后advance推进(self, registry):
        ctx = AgentContext(current_phase="planning")
        ctrl = PhaseController(ctx, registry)
        ctrl.mark_phase_done("planning")
        advanced = ctrl.advance()
        assert advanced is True
        assert ctrl.current_phase == "search"
        assert "planning" in ctx.completed_phases

    def test_全部phase完成后advance返回False(self, registry):
        ctx = AgentContext(
            current_phase="render",
            completed_phases=set(PhaseController.PHASE_ORDER) - {"render"},
        )
        ctrl = PhaseController(ctx, registry)
        ctrl.mark_phase_done("render")
        advanced = ctrl.advance()
        assert advanced is False
        assert ctx.finished is True
