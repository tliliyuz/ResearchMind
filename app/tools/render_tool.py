"""render_tool —— 包装 run_render。"""

from app.pipeline.renderer import run_render
from app.tools.base import PhaseHandlerTool

render_tool = PhaseHandlerTool(
    name="render_tool",
    description="Render 阶段：将综合结果渲染为最终 Markdown 报告",
    mapped_phase="render",
    handler=run_render,
)
