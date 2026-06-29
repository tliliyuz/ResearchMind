"""AgentContext —— 单次 Agent 运行的内存状态。

包含当前 phase、已完成 phase、迭代计数、最后 step id、结束标记等。
序列化后保存到 execution_context["agent_context"] 用于断点续跑。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import STEP_TYPE_ENUM


@dataclass
class AgentContext:
    """单次 Agent 运行内存状态。"""

    current_phase: str | None = None
    completed_phases: set[str] = field(default_factory=set)
    iteration_count: int = 0
    last_step_id: str | None = None
    finished: bool = False
    finish_reason: str | None = None

    def to_dict(self) -> dict:
        """序列化为可 JSON 序列化的 dict。"""
        return {
            "current_phase": self.current_phase,
            "completed_phases": sorted(self.completed_phases),
            "iteration_count": self.iteration_count,
            "last_step_id": self.last_step_id,
            "finished": self.finished,
            "finish_reason": self.finish_reason,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "AgentContext":
        """从 dict 反序列化。"""
        if not isinstance(data, dict):
            return cls()

        valid_phases = set(STEP_TYPE_ENUM)
        completed = {
            str(p)
            for p in data.get("completed_phases", [])
            if p in valid_phases
        }
        return cls(
            current_phase=data.get("current_phase"),
            completed_phases=completed,
            iteration_count=int(data.get("iteration_count", 0) or 0),
            last_step_id=data.get("last_step_id"),
            finished=bool(data.get("finished", False)),
            finish_reason=data.get("finish_reason"),
        )
