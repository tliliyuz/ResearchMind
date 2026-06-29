"""Agent Prompt 构建单元测试。"""

import pytest

from app.agent.context import AgentContext
from app.agent.prompts import build_agent_system_prompt, build_phase_instruction
from app.agent.state import PhaseController
from app.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    reg = ToolRegistry()
    return reg


class TestBuildAgentSystemPrompt:
    def test_包含当前阶段主要工具(self, registry):
        ctx = AgentContext(current_phase="search", completed_phases={"planning"})
        controller = PhaseController(ctx, registry)

        prompt = build_agent_system_prompt(controller)

        assert "当前阶段的主要工具是：search_tool" in prompt
        assert "你必须调用它来完成本阶段的实际工作" in prompt

    def test_每个phase都有主要工具映射(self, registry):
        from app.agent.prompts import _PHASE_PRIMARY_TOOL
        from app.models.enums import STEP_TYPE_ENUM

        assert set(_PHASE_PRIMARY_TOOL.keys()) == set(STEP_TYPE_ENUM)
        for phase in STEP_TYPE_ENUM:
            ctx = AgentContext(current_phase=phase)
            controller = PhaseController(ctx, registry)
            prompt = build_agent_system_prompt(controller)
            assert f"当前阶段的主要工具是：{_PHASE_PRIMARY_TOOL[phase]}" in prompt

    def test_明确限制memory_tool使用(self, registry):
        ctx = AgentContext(current_phase="search")
        controller = PhaseController(ctx, registry)

        prompt = build_agent_system_prompt(controller)

        assert "memory_tool 仅用于必要时的快速回顾或追加备注" in prompt
        assert "不能替代当前阶段的主要工具" in prompt
        assert "禁止连续多次调用" in prompt

    def test_finish_tool描述正确(self, registry):
        ctx = AgentContext(current_phase="search")
        controller = PhaseController(ctx, registry)

        prompt = build_agent_system_prompt(controller)

        assert "系统会自动推进到下一阶段" in prompt
        assert "只有当所有阶段完成或需要提前终止时，才调用 finish_tool" in prompt


class TestBuildPhaseInstruction:
    def test_包含当前阶段主要工具(self, registry):
        ctx = AgentContext(current_phase="search", completed_phases={"planning"})
        controller = PhaseController(ctx, registry)

        instruction = build_phase_instruction(controller)

        assert instruction["role"] == "user"
        assert "当前阶段：search" in instruction["content"]
        assert "请直接调用 search_tool 执行本阶段工作" in instruction["content"]
        assert "memory_tool 仅用于必要时快速回顾上下文" in instruction["content"]
