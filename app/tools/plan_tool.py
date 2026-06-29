"""plan_tool —— 包装 run_planning。"""

from app.pipeline.planner import run_planning
from app.tools.base import PhaseHandlerTool

plan_tool = PhaseHandlerTool(
    name="plan_tool",
    description="Planning 阶段：将研究主题拆解为子问题，生成研究计划",
    mapped_phase="planning",
    handler=run_planning,
)
