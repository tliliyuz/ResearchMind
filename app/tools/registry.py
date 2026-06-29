"""ToolRegistry —— Tool 注册中心，负责 schema 生成、查找、phase 过滤。"""

from __future__ import annotations

from typing import Any

from app.tools.base import PhaseHandlerTool, Tool
from app.tools.evidence_graph_tool import evidence_graph_tool
from app.tools.fetch_tool import fetch_tool
from app.tools.finish_tool import FinishTool
from app.tools.memory_tool import MemoryTool
from app.tools.plan_tool import plan_tool
from app.tools.render_tool import render_tool
from app.tools.rerank_tool import rerank_tool
from app.tools.search_tool import search_tool
from app.tools.synthesis_tool import synthesis_tool


class ToolRegistry:
    """Tool 注册中心。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._finish_tool = FinishTool()

    def register(self, tool: Tool) -> "ToolRegistry":
        """注册一个 Tool。"""
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Tool | None:
        """按名称获取 Tool。"""
        if name == self._finish_tool.name:
            return self._finish_tool
        return self._tools.get(name)

    def get_finish_tool(self) -> FinishTool:
        """获取 finish_tool。"""
        return self._finish_tool

    def list_tools(self, phase: str | None = None) -> list[Tool]:
        """列出所有 Tool；指定 phase 时只返回 mapped_phase 匹配的 Tool（不含 finish_tool）。"""
        tools = list(self._tools.values())
        if phase is not None:
            tools = [t for t in tools if getattr(t, "mapped_phase", None) == phase]
        return tools

    def to_openai_schema(self, phase: str | None = None) -> list[dict[str, Any]]:
        """生成 OpenAI Function Calling 格式的工具 schema 列表。"""
        schemas: list[dict[str, Any]] = []
        names: set[str] = set()
        for tool in self.list_tools(phase):
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            })
            names.add(tool.name)

        # 全局 Tool 始终可用
        for global_tool in (self._finish_tool, self.get(MemoryTool.name)):
            if global_tool is None or global_tool.name in names:
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": global_tool.name,
                    "description": global_tool.description,
                    "parameters": global_tool.parameters_schema,
                },
            })
            names.add(global_tool.name)
        return schemas


def build_default_tool_registry(phase_handlers: dict[str, Any] | None = None) -> ToolRegistry:
    """构建默认 ToolRegistry。

    Args:
        phase_handlers: 可选的 phase handler 字典；未提供时使用默认 handler。

    Returns:
        ToolRegistry 实例
    """
    if phase_handlers is None:
        from app.services.pipeline_orchestrator import build_default_phase_handlers
        phase_handlers = build_default_phase_handlers()

    registry = ToolRegistry()
    mapping = [
        ("plan_tool", "planning", "Planning 阶段：将研究主题拆解为子问题，生成研究计划"),
        ("search_tool", "search", "Search 阶段：根据子问题调用搜索 API 获取候选来源"),
        ("fetch_tool", "fetch", "Fetch 阶段：抓取并提取网页正文内容"),
        ("rerank_tool", "rerank", "Rerank 阶段：对候选来源进行粗筛精排，输出 Evidence 列表"),
        ("synthesis_tool", "synthesis", "Synthesis 阶段：跨来源综合、发现冲突与知识缺口"),
        ("evidence_graph_tool", "evidence_graph", "Evidence Graph 阶段：构建结构化的来源与证据图谱"),
        ("render_tool", "render", "Render 阶段：将综合结果渲染为最终 Markdown 报告"),
    ]

    for name, phase, description in mapping:
        handler = phase_handlers.get(phase)
        if handler is None:
            continue
        registry.register(PhaseHandlerTool(
            name=name,
            description=description,
            mapped_phase=phase,
            handler=handler,
        ))

    # memory_tool 全局可用，无 phase 映射
    registry.register(MemoryTool())

    return registry
