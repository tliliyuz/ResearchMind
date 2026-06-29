"""PhaseController —— 维护 7 phase 顺序、过滤可用 Tool、判定 phase 完成与推进。

Phase-Locked Loop 的核心：Agent 仍按固定顺序推进，但在每个 phase 内可多次调用 Tool。
"""

from __future__ import annotations

from app.models.enums import STEP_TYPE_ENUM
from app.tools.base import Tool
from app.tools.finish_tool import FinishTool


class PhaseController:
    """Phase 顺序与可用 Tool 控制器。"""

    PHASE_ORDER: list[str] = list(STEP_TYPE_ENUM)

    def __init__(self, agent_context, tool_registry):
        """初始化。

        Args:
            agent_context: AgentContext 实例
            tool_registry: ToolRegistry 实例
        """
        self._ctx = agent_context
        self._registry = tool_registry

        # 恢复到当前应执行的 phase
        self._ensure_current_phase()

    @property
    def current_phase(self) -> str | None:
        return self._ctx.current_phase

    def _ensure_current_phase(self) -> None:
        """确保 current_phase 指向第一个未完成的 phase。"""
        if self._ctx.current_phase is not None and self._ctx.current_phase not in self._ctx.completed_phases:
            return
        for phase in self.PHASE_ORDER:
            if phase not in self._ctx.completed_phases:
                self._ctx.current_phase = phase
                return
        self._ctx.current_phase = self.PHASE_ORDER[-1]

    def get_available_tools(self) -> list[Tool]:
        """返回当前 phase 可用的 Tool 列表（始终包含 finish_tool）。"""
        phase = self._ctx.current_phase
        tools: list[Tool] = []
        if phase is not None:
            tools.extend(self._registry.list_tools(phase))
        tools.append(self._registry.get_finish_tool())
        return tools

    def is_tool_available(self, name: str) -> bool:
        """指定 Tool 是否在当前 phase 可用。"""
        return any(t.name == name for t in self.get_available_tools())

    def mark_phase_done(self, phase: str | None) -> None:
        """标记指定 phase 已完成。"""
        if phase:
            self._ctx.completed_phases.add(phase)

    def advance(self) -> bool:
        """推进到下一个未完成的 phase。

        Returns:
            True: 成功推进到下一个 phase
            False: 所有 phase 均已完成
        """
        current = self._ctx.current_phase
        if current and current not in self._ctx.completed_phases:
            # 当前 phase 未完成时不推进（由调用方先 mark_phase_done）
            return True

        started = False
        for phase in self.PHASE_ORDER:
            if not started:
                if phase == current:
                    started = True
                continue
            if phase not in self._ctx.completed_phases:
                self._ctx.current_phase = phase
                return True

        # 全部完成
        self._ctx.current_phase = None
        self._ctx.finished = True
        return False

    @property
    def all_phases_completed(self) -> bool:
        """所有 7 phase 是否均已完成。"""
        return set(self.PHASE_ORDER).issubset(self._ctx.completed_phases)

    @property
    def current_phase_done(self) -> bool:
        """当前 phase 是否已完成。"""
        return self._ctx.current_phase in self._ctx.completed_phases
