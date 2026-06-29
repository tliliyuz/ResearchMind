"""search_tool —— 包装 run_search。"""

from app.pipeline.searcher import run_search
from app.tools.base import PhaseHandlerTool

search_tool = PhaseHandlerTool(
    name="search_tool",
    description="Search 阶段：根据子问题调用搜索 API 获取候选来源",
    mapped_phase="search",
    handler=run_search,
)
