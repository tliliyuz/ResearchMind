"""rerank_tool —— 包装 run_rerank。"""

from app.pipeline.reranker import run_rerank
from app.tools.base import PhaseHandlerTool

_RERANK_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "top_k": {
            "type": "integer",
            "description": "（可选）希望保留的 Top-K 候选数量",
        },
        "reason": {
            "type": "string",
            "description": "（可选）说明本次精排的侧重点（如优先权威性/多样性）",
        },
    },
    "required": [],
}

rerank_tool = PhaseHandlerTool(
    name="rerank_tool",
    description="Rerank 阶段：对候选来源进行粗筛精排，输出 Evidence 列表",
    mapped_phase="rerank",
    handler=run_rerank,
    parameters_schema=_RERANK_TOOL_SCHEMA,
)
