"""AgentLoop —— LLM 循环、Tool Call 解析、Observation 处理。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.exceptions import AgentLoopExhaustedError
from app.agent.memory import ReActEntry, WorkingMemory
from app.agent.prompts import build_agent_system_prompt, build_phase_instruction
from app.agent.state import PhaseController
from app.config import settings
from app.core.llm import chat_completion
from app.pipeline.sse_bridge import (
    EVENT_AGENT_ACTION,
    EVENT_AGENT_OBSERVATION,
    EVENT_AGENT_THOUGHT,
    SSEBridge,
)
from app.tools.base import Tool, ToolCall, ToolContext, ToolResult
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolExecutionResult:
    """Tool 执行回调返回结果，包含 ToolResult 与关联 Step ID。"""

    result: ToolResult
    step_id: str | None = None


ExecuteToolCallback = Callable[[Tool, ToolCall], Awaitable[ToolExecutionResult]]


class AgentLoop:
    """Agent 核心循环：LLM → Tool Call → Observation → 下一循环。"""

    def __init__(
        self,
        phase_controller: PhaseController,
        working_memory: WorkingMemory,
        sse_bridge: SSEBridge,
        max_iterations: int | None = None,
    ):
        self._phase_controller = phase_controller
        self._working_memory = working_memory
        self._sse = sse_bridge
        self._max_iterations = max_iterations or settings.MAX_AGENT_ITERATIONS

    async def run(self, tool_context: ToolContext, execute_callback: ExecuteToolCallback) -> None:
        """运行 Agent Loop 直到结束或迭代耗尽。

        Args:
            tool_context: Tool 执行上下文（agent_context 会被更新）
            execute_callback: Tool 执行回调，接收 Tool 和 ToolCall，返回 ToolResult
        """
        agent_ctx = tool_context.agent_context
        iteration = agent_ctx.iteration_count or 0

        while not agent_ctx.finished and iteration < self._max_iterations:
            iteration += 1
            agent_ctx.iteration_count = iteration
            current_phase = self._phase_controller.current_phase

            if current_phase is None:
                logger.info("所有 phase 已完成，结束 Agent Loop")
                agent_ctx.finished = True
                break

            messages = self._build_messages()
            available_tools = self._phase_controller.get_available_tools()
            tool_schemas = [
                self._tool_to_schema(t) for t in available_tools
            ]

            try:
                llm_result = await chat_completion(
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent Loop LLM 调用失败: %s", exc)
                # 记录失败 observation 后继续，给 LLM 机会在下一轮恢复
                self._working_memory.add(ReActEntry(
                    iteration=iteration,
                    phase=current_phase,
                    thought=None,
                    tool_name=None,
                    observation=f"LLM 调用失败: {exc}",
                ))
                continue

            if llm_result.reasoning_content:
                await self._sse.publish(EVENT_AGENT_THOUGHT, {
                    "iteration": iteration,
                    "phase": current_phase,
                    "thought": llm_result.reasoning_content,
                })

            tool_calls = llm_result.tool_calls or []
            if not tool_calls:
                # LLM 未返回 Tool 调用，记录 content 为观察后继续
                self._working_memory.add(ReActEntry(
                    iteration=iteration,
                    phase=current_phase,
                    thought=llm_result.reasoning_content,
                    observation=llm_result.content or "LLM 未返回 Tool 调用",
                ))
                continue

            for tool_call in tool_calls:
                tool = self._resolve_tool(tool_call.name, available_tools)
                await self._sse.publish(EVENT_AGENT_ACTION, {
                    "iteration": iteration,
                    "phase": current_phase,
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "arguments": tool_call.arguments,
                })

                if tool is None:
                    observation = f"Tool '{tool_call.name}' 在当前 phase 不可用"
                    exec_result = ToolExecutionResult(
                        result=ToolResult(
                            success=False,
                            output={},
                            observation=observation,
                            error_message=observation,
                        ),
                        step_id=None,
                    )
                else:
                    exec_result = await execute_callback(tool, tool_call)
                    observation = exec_result.result.observation

                result = exec_result.result
                await self._sse.publish(EVENT_AGENT_OBSERVATION, {
                    "iteration": iteration,
                    "phase": current_phase,
                    "tool_call_id": tool_call.id,
                    "tool_name": tool_call.name,
                    "observation": observation,
                    "success": result.success,
                })

                self._working_memory.add(ReActEntry(
                    iteration=iteration,
                    phase=current_phase,
                    thought=llm_result.reasoning_content,
                    tool_name=tool_call.name,
                    tool_call_id=tool_call.id,
                    arguments=tool_call.arguments,
                    observation=observation,
                    tool_output_summary=self._summarize_output(result.output),
                    step_id=exec_result.step_id,
                ))

                # 当前 phase 的 primary tool 成功执行一次即标记完成
                if (
                    tool is not None
                    and tool.mapped_phase == current_phase
                    and result.success
                ):
                    self._phase_controller.mark_phase_done(current_phase)

            # 本轮 tool calls 处理完后，若当前 phase 已完成则推进
            if self._phase_controller.current_phase_done:
                advanced = self._phase_controller.advance()
                if not advanced:
                    logger.info("所有 phase 已完成，Agent Loop 结束")
                    agent_ctx.finished = True
                    break

        if not agent_ctx.finished and iteration >= self._max_iterations:
            logger.error("Agent Loop 达到最大迭代次数: %d", self._max_iterations)
            raise AgentLoopExhaustedError(self._max_iterations)

    def _build_messages(self) -> list[dict[str, Any]]:
        """构造 LLM 消息列表。"""
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_agent_system_prompt(self._phase_controller),
            },
        ]
        messages.extend(self._working_memory.to_messages())
        messages.append(build_phase_instruction(self._phase_controller))
        return messages

    def _resolve_tool(self, name: str, available_tools: list[Tool]) -> Tool | None:
        """在可用 Tool 列表中查找指定 Tool。"""
        for tool in available_tools:
            if tool.name == name:
                return tool
        return None

    @staticmethod
    def _tool_to_schema(tool: Tool) -> dict[str, Any]:
        """将 Tool 转为 OpenAI Function schema。"""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            },
        }

    @staticmethod
    def _summarize_output(output: dict[str, Any]) -> dict[str, Any]:
        """对 Tool output 做摘要，避免 prompt 过长。"""
        if not isinstance(output, dict):
            return {}
        # 仅保留关键计数字段；memory_tool 追加的 note 也需保留以便回溯
        keys = [
            "sub_questions", "total_results", "successful", "evidence_count",
            "clusters_count", "conflicts_count", "gaps_count", "item_count",
            "sections_count", "citations_count", "memory_note",
        ]
        summary = {k: output[k] for k in keys if k in output}
        if not summary:
            summary = {"keys": list(output.keys())[:5]}
        return summary
