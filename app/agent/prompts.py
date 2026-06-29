"""Agent 系统 Prompt 构建。"""

from __future__ import annotations

from app.agent.state import PhaseController


_PHASE_ACTION_GUIDE: dict[str, str] = {
    "planning": "拆解研究主题为若干子问题，生成研究计划。",
    "search": "根据子问题调用搜索，获取候选来源。",
    "fetch": "对候选 URL 进行网页抓取与正文提取。",
    "rerank": "对抓取结果进行粗筛精排，输出高质量 Evidence 列表。",
    "synthesis": "跨来源综合信息，识别冲突、缺口与共识。",
    "evidence_graph": "将 Evidence 组织为结构化的来源与证据图谱。",
    "render": "将综合结果渲染为最终 Markdown 报告。",
}

_PHASE_PRIMARY_TOOL: dict[str, str] = {
    "planning": "plan_tool",
    "search": "search_tool",
    "fetch": "fetch_tool",
    "rerank": "rerank_tool",
    "synthesis": "synthesis_tool",
    "evidence_graph": "evidence_graph_tool",
    "render": "render_tool",
}


def build_agent_system_prompt(controller: PhaseController) -> str:
    """构建 ReAct + Phase 锁定的 system prompt。"""
    phase_order = " → ".join(controller.PHASE_ORDER)
    current = controller.current_phase or "planning"
    completed = ", ".join(sorted(controller._ctx.completed_phases)) or "无"
    guide = _PHASE_ACTION_GUIDE.get(current, "完成当前阶段目标。")
    primary_tool = _PHASE_PRIMARY_TOOL.get(current, "对应阶段工具")

    return (
        "你是一个研究型 Agent，负责调用 Tool 完成用户的研究任务。\n"
        "你必须遵循以下规则：\n"
        "1. 整体按固定顺序推进：" + phase_order + "\n"
        "2. 当前阶段锁定为：" + current + "\n"
        "3. 你只能调用当前阶段允许的 Tool、finish_tool 和 memory_tool；调用其他 Tool 会被拒绝。\n"
        "4. 当前阶段目标达成后，系统会自动推进到下一阶段；只有当所有阶段完成或需要提前终止时，才调用 finish_tool。\n"
        "5. 如果当前阶段需要多次调用（如多次搜索），可在同一阶段内重复调用对应 Tool。\n"
        "6. 已完成阶段：" + completed + "\n"
        "7. 每次回复前先输出简要思考过程（reasoning），然后给出 Tool 调用。\n"
        "8. 除非明确调用 finish_tool，否则不要离开当前阶段。\n"
        "9. 当前阶段的主要工具是：" + primary_tool + "；你必须调用它来完成本阶段的实际工作。\n"
        "10. memory_tool 仅用于必要时的快速回顾或追加备注，不能替代当前阶段的主要工具，禁止连续多次调用。\n\n"
        "当前阶段行动指引：" + guide + "\n"
    )


def build_phase_instruction(controller: PhaseController) -> dict[str, str]:
    """构建当前 phase 的用户级指令消息。"""
    current = controller.current_phase or "planning"
    primary_tool = _PHASE_PRIMARY_TOOL.get(current, "对应阶段工具")
    return {
        "role": "user",
        "content": (
            f"当前阶段：{current}。"
            f"请直接调用 {primary_tool} 执行本阶段工作；"
            "memory_tool 仅用于必要时快速回顾上下文，不可替代阶段工具。"
            "若当前阶段目标已达成，请调用 finish_tool。"
        ),
    }
