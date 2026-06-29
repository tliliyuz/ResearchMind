"""render_tool —— 包装 run_render。"""

from app.pipeline.renderer import run_render
from app.tools.base import PhaseHandlerTool

_RENDER_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": "（可选）说明本次渲染希望突出的报告重点",
        },
    },
    "required": [],
}

render_tool = PhaseHandlerTool(
    name="render_tool",
    description="Render 阶段：将综合结果渲染为最终 Markdown 报告",
    mapped_phase="render",
    handler=run_render,
    parameters_schema=_RENDER_TOOL_SCHEMA,
)
