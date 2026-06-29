"""evidence_graph_tool —— 包装 run_evidence_graph。"""

from app.pipeline.evidence_graph import run_evidence_graph
from app.tools.base import PhaseHandlerTool

_EVIDENCE_GRAPH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": "（可选）说明本次构建图谱的侧重点",
        },
    },
    "required": [],
}

evidence_graph_tool = PhaseHandlerTool(
    name="evidence_graph_tool",
    description="Evidence Graph 阶段：构建结构化的来源与证据图谱",
    mapped_phase="evidence_graph",
    handler=run_evidence_graph,
    parameters_schema=_EVIDENCE_GRAPH_TOOL_SCHEMA,
)
