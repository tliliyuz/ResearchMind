"""Tool 抽象基类 —— MCP 风格的统一 Tool 接口。

对齐 agent_design.md §6.1：
- ToolResult：Tool 执行产出
- ToolCall：LLM 发起的单次 Tool 调用
- ToolContext：Tool 执行时注入的上下文
- Tool Protocol：所有 Tool 必须实现的接口
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import AgentContext
from app.core.trace_recorder import TraceRecorder
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import SSEBridge


@dataclass
class ToolResult:
    """Tool 执行结果。"""

    success: bool
    output: dict[str, Any]
    observation: str
    error_message: str | None = None
    cost: dict[str, Any] | None = None
    duration_ms: int = 0


@dataclass
class ToolCall:
    """LLM 发起的 Tool 调用描述。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolContext:
    """Tool 执行上下文。"""

    task: ResearchTask
    step: ResearchStep
    session: AsyncSession
    sse_bridge: SSEBridge
    trace_recorder: TraceRecorder
    agent_context: AgentContext


@runtime_checkable
class Tool(Protocol):
    """Tool 协议。

    所有 Tool 必须提供 name / description / parameters_schema，
    并可通过 execute(ctx, **params) 异步执行。
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    mapped_phase: str | None = None

    async def execute(self, ctx: ToolContext, **params: Any) -> ToolResult:
        """执行 Tool，返回 ToolResult。"""
        ...


class PhaseHandlerTool:
    """薄适配器：将现有 phase handler 包装为 Tool。

    直接调用 handler(task, step, session, sse_bridge)，不修改 handler 内部逻辑。
    """

    def __init__(
        self,
        name: str,
        description: str,
        mapped_phase: str,
        handler: Any,
        parameters_schema: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        self.mapped_phase = mapped_phase
        self._handler = handler
        self.parameters_schema = parameters_schema or {"type": "object", "properties": {}}

    async def execute(self, ctx: ToolContext, **params: Any) -> ToolResult:
        """调用底层 phase handler 并包装结果。"""
        import time

        t0 = time.perf_counter()
        try:
            output = await self._handler(ctx.task, ctx.step, ctx.session, ctx.sse_bridge)
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - t0) * 1000)
            return ToolResult(
                success=False,
                output={},
                observation=f"{self.mapped_phase} 阶段执行失败: {exc}",
                error_message=str(exc),
                duration_ms=duration_ms,
            )

        duration_ms = int((time.perf_counter() - t0) * 1000)
        output_dict = output if isinstance(output, dict) else {"result": str(output)}
        return ToolResult(
            success=True,
            output=output_dict,
            observation=f"{self.mapped_phase} 阶段执行完成，产出 {len(output_dict)} 个字段",
            duration_ms=duration_ms,
        )
