"""fetch_tool —— 包装 run_fetch。"""

from app.pipeline.fetcher import run_fetch
from app.tools.base import PhaseHandlerTool

fetch_tool = PhaseHandlerTool(
    name="fetch_tool",
    description="Fetch 阶段：抓取并提取网页正文内容",
    mapped_phase="fetch",
    handler=run_fetch,
)
