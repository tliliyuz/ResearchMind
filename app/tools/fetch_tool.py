"""fetch_tool —— 包装 run_fetch。"""

from app.pipeline.fetcher import run_fetch
from app.tools.base import PhaseHandlerTool

_FETCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "target_url": {
            "type": "string",
            "description": "（可选）指定优先抓取的 URL",
        },
        "reason": {
            "type": "string",
            "description": "（可选）说明本次抓取的目标或关注点",
        },
    },
    "required": [],
}

fetch_tool = PhaseHandlerTool(
    name="fetch_tool",
    description="Fetch 阶段：抓取并提取网页正文内容",
    mapped_phase="fetch",
    handler=run_fetch,
    parameters_schema=_FETCH_TOOL_SCHEMA,
)
