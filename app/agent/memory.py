"""Working Memory —— 单次任务内的 ReAct Trace。

Phase 1 仅内存存储，最终随 execution_context.agent_context 序列化到 DB。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ReActEntry:
    """一条 ReAct Trace 记录。"""

    iteration: int
    phase: str
    thought: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    arguments: dict[str, Any] | None = field(default_factory=dict)
    observation: str | None = None
    tool_output_summary: dict[str, Any] | None = field(default_factory=dict)
    step_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict。"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReActEntry":
        """从 dict 反序列化。"""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                ts = datetime.now(timezone.utc)
        if not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        return cls(
            iteration=int(data.get("iteration", 0)),
            phase=str(data.get("phase", "")),
            thought=data.get("thought"),
            tool_name=data.get("tool_name"),
            tool_call_id=data.get("tool_call_id"),
            arguments=data.get("arguments") or {},
            observation=data.get("observation"),
            tool_output_summary=data.get("tool_output_summary") or {},
            step_id=data.get("step_id"),
            timestamp=ts,
        )


class WorkingMemory:
    """内存级 ReAct Trace，限制最大条目数。"""

    def __init__(self, max_entries: int = 20):
        self._max_entries = max(max_entries, 1)
        self._entries: list[ReActEntry] = []

    def add(self, entry: ReActEntry) -> None:
        """添加一条记录；超过上限时丢弃最旧条目。"""
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

    def recent(self, n: int | None = None) -> list[ReActEntry]:
        """返回最近 n 条记录。"""
        if n is None or n < 0:
            return list(self._entries)
        return list(self._entries[-n:])

    def to_messages(self) -> list[dict[str, Any]]:
        """转换为 OpenAI 消息列表格式（简化文本形式）。"""
        messages: list[dict[str, Any]] = []
        for entry in self._entries:
            lines: list[str] = []
            if entry.thought:
                lines.append(f"思考：{entry.thought}")
            if entry.tool_name:
                args = entry.arguments or {}
                lines.append(f"动作：调用 {entry.tool_name}({args})")
            if entry.observation:
                lines.append(f"观察：{entry.observation}")
            if not lines:
                continue
            messages.append({
                "role": "assistant",
                "content": "\n".join(lines),
            })
        return messages

    def to_dict_list(self) -> list[dict[str, Any]]:
        """序列化为 dict 列表。"""
        return [entry.to_dict() for entry in self._entries]

    @classmethod
    def from_dict_list(cls, items: list[dict[str, Any]] | None, max_entries: int = 20) -> "WorkingMemory":
        """从 dict 列表重建 WorkingMemory。"""
        memory = cls(max_entries=max_entries)
        if not items:
            return memory
        valid_items = [item for item in items if isinstance(item, dict)]
        for item in valid_items[-max_entries:]:
            try:
                memory.add(ReActEntry.from_dict(item))
            except Exception:
                continue
        return memory
