"""memory_tool —— 读/写当前任务的 Working Memory。

Phase 2 仅支持 Working Memory（内存级 ReAct Trace）。
Long Memory 相关操作返回明确的未实现提示，不建表、不持久化。
"""

from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext, ToolResult


class MemoryTool:
    """读/写当前任务 Working Memory 的 Tool。"""

    name: str = "memory_tool"
    description: str = (
        "【辅助工具】读/写当前任务的 Working Memory。"
        "仅在需要快速回顾历史思考、追加备注或获取当前记忆摘要时使用。"
        "不能替代当前阶段的主要工具，禁止连续多次调用。"
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
            # Phase 3 修正：ReActEntry 统一由 AgentLoop 记录，Tool 内部不再自行写入，
            # 避免同一操作产生重复条目。memory_note 通过 output 由 AgentLoop 摘要保留。
            return ToolResult(
                success=True,
                output={"operation": operation, "entries_count": len(memory.recent()), "memory_note": content},
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
            # Phase 3 修正：read 不再把完整历史拼进 observation，防止 prompt/DB 指数膨胀。
            # 仅返回统计摘要，具体条目由 AgentLoop 通过 output 摘要保留关键信息。
            if not entries:
                observation = "Working Memory 为空"
            else:
                phases = [entry.phase for entry in entries if entry.phase]
                tools = [entry.tool_name for entry in entries if entry.tool_name]
                observation = (
                    f"已返回最近 {len(entries)} 条 Working Memory 记录"
                    f"（最近 phase={phases[-1] if phases else '无'}，"
                    f"最近 tool={tools[-1] if tools else '无'}）"
                )
            return ToolResult(
                success=True,
                output={"entries_count": len(entries), "limit": limit},
                observation=observation,
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
