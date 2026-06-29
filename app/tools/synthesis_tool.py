"""synthesis_tool —— 包装 run_synthesis。"""

from app.pipeline.synthesizer import run_synthesis
from app.tools.base import PhaseHandlerTool

_SYNTHESIS_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "focus_cluster": {
            "type": "string",
            "description": "（可选）指定优先综合的聚类/主题名称",
        },
        "reason": {
            "type": "string",
            "description": "（可选）说明本次综合希望重点回答的子问题",
        },
    },
    "required": [],
}

synthesis_tool = PhaseHandlerTool(
    name="synthesis_tool",
    description="Synthesis 阶段：跨来源综合、发现冲突与知识缺口",
    mapped_phase="synthesis",
    handler=run_synthesis,
    parameters_schema=_SYNTHESIS_TOOL_SCHEMA,
)
