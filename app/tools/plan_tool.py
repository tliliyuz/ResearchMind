"""plan_tool —— 包装 run_planning。"""

from app.pipeline.planner import run_planning
from app.tools.base import PhaseHandlerTool

_PLAN_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": "（可选）说明本次规划侧重点或需要调整的方向",
        },
    },
    "required": [],
}

plan_tool = PhaseHandlerTool(
    name="plan_tool",
    description="Planning 阶段：将研究主题拆解为子问题，生成研究计划",
    mapped_phase="planning",
    handler=run_planning,
    parameters_schema=_PLAN_TOOL_SCHEMA,
)
