"""memory_tool —— 读/写当前任务的 Working Memory。

Phase 2 仅支持 Working Memory（内存级 ReAct Trace）。
Long Memory 相关操作返回明确的未实现提示，不建表、不持久化。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agent.memory import ReActEntry
from app.tools.base import ToolContext, ToolResult


class MemoryTool:
    """读/写当前任务 Working Memory 的 Tool。"""

    name: str = "memory_tool"
    description: str = (
        "读/写当前任务的 Working Memory。"
        "可用于回顾历史思考、追加备注或获取当前记忆摘要。"
        "Long Memory 暂未实现。"
    )
    mapped_phase: str | None = None
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "append", "summary"],
                "description": "操作类型：read（读取最近条目）、write/append（追加条目）、summary（统计摘要）",
            },
            "content": {
                "type": "string",
                "description": "（可选）write/append 时的自定义内容",
            },
            "limit": {
                "type": "integer",
                "description": "（可选）read 时返回的最近条目数，默认 5",
            },
        },
        "required": ["operation"],
    }

    async def execute(self, ctx: ToolContext, **params: Any) -> ToolResult:
        """执行 memory 操作。"""
        operation = str(params.get("operation", "")).lower()
        memory = ctx.working_memory

        if operation in ("write", "append"):
            content = params.get("content") or ""
            entry = ReActEntry(
                iteration=ctx.agent_context.iteration_count,
                phase=ctx.agent_context.current_phase or "unknown",
                thought=None,
                tool_name=self.name,
                tool_call_id=None,
                arguments={"operation": operation, "content": content},
                observation=None,
                tool_output_summary={"memory_note": content},
                step_id=ctx.agent_context.last_step_id,
                timestamp=datetime.now(timezone.utc),
            )
            memory.add(entry)
            return ToolResult(
                success=True,
                output={"operation": operation, "entries_count": len(memory.recent())},
                observation=f"已向 Working Memory 追加 {len(content)} 字符的备注",
            )

        if operation == "read":
            limit = params.get("limit")
            try:
                limit = int(limit) if limit is not None else 5
            except (TypeError, ValueError):
                return ToolResult(
                    success=False,
                    output={},
                    observation="参数校验失败: 'limit' 应为整数",
                    error_message="tool_param_validation_failed",
                )
            entries = memory.recent(n=limit)
            lines = []
            for entry in entries:
                lines.append(
                    f"[iter={entry.iteration} phase={entry.phase} tool={entry.tool_name}] "
                    f"{entry.tool_output_summary.get('memory_note', entry.observation or '')}"
                )
            return ToolResult(
                success=True,
                output={"entries_count": len(entries), "limit": limit},
                observation="\n".join(lines) if lines else "Working Memory 为空",
            )

        if operation == "summary":
            entries = memory.recent()
            phases = [entry.phase for entry in entries if entry.phase]
            tools = [entry.tool_name for entry in entries if entry.tool_name]
            return ToolResult(
                success=True,
                output={
                    "total_entries": len(entries),
                    "latest_phase": phases[-1] if phases else None,
                    "latest_tool": tools[-1] if tools else None,
                },
                observation=(
                    f"Working Memory 共 {len(entries)} 条，"
                    f"最近 phase={phases[-1] if phases else '无'}，"
                    f"最近 tool={tools[-1] if tools else '无'}"
                ),
            )

        # Long Memory 等未实现操作
        return ToolResult(
            success=False,
            output={},
            observation="Long Memory 在 Phase 2 未实现",
            error_message="long_memory_not_implemented",
        )
