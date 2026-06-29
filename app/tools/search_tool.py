"""search_tool —— 包装 run_search。"""

from app.pipeline.searcher import run_search
from app.tools.base import PhaseHandlerTool

_SEARCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "focus_sub_question_index": {
            "type": "integer",
            "description": "（可选）优先处理的子问题序号（从 0 开始）",
        },
        "reason": {
            "type": "string",
            "description": "（可选）说明本次搜索希望重点覆盖的方向",
        },
    },
    "required": [],
}

search_tool = PhaseHandlerTool(
    name="search_tool",
    description="Search 阶段：根据子问题调用搜索 API 获取候选来源",
    mapped_phase="search",
    handler=run_search,
    parameters_schema=_SEARCH_TOOL_SCHEMA,
)
