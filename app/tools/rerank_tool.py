"""rerank_tool —— 包装 run_rerank。"""

from app.pipeline.reranker import run_rerank
from app.tools.base import PhaseHandlerTool

rerank_tool = PhaseHandlerTool(
    name="rerank_tool",
    description="Rerank 阶段：对候选来源进行粗筛精排，输出 Evidence 列表",
    mapped_phase="rerank",
    handler=run_rerank,
)
