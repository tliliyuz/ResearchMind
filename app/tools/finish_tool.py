"""finish_tool —— 供 LLM 显式结束 Agent Loop。"""

from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext, ToolResult


class FinishTool:
    """结束 Agent Loop 的 Tool。"""

    name: str = "finish_tool"
    description: str = (
        "显式结束当前 Agent 运行。"
        "当当前 phase 的目标已达成或需要提前终止时调用。"
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "结束原因",
            },
        },
        "required": [],
    }
    mapped_phase: str | None = None

    async def execute(self, ctx: ToolContext, **params: Any) -> ToolResult:
        """标记 Agent 结束。"""
        ctx.agent_context.finished = True
        ctx.agent_context.finish_reason = params.get("reason") or "finished_by_llm"
        return ToolResult(
            success=True,
            output={"finished": True, "reason": ctx.agent_context.finish_reason},
            observation="Agent 已显式结束运行",
        )
