"""Search 阶段 —— Tavily API 多子问题搜索 + URL 去重。

§3.4 实现完整逻辑（Tavily 调用 + 失败重试 + 跨子问题去重）。
当前为最小 stub，Pipeline Orchestrator 可调通全链路。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep

logger = logging.getLogger(__name__)


async def run_search(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge,  # SSEBridge
) -> dict:
    """执行 Search 阶段（stub）。

    §3.4 将替换为：
    1. 读取 Planning 产出的 SubQuestion[]
    2. 对每个 SubQuestion 调用 Tavily Search API
       （search_depth=advanced, max_results=5）
    3. 跨子问题 URL 去重
    4. 单子问题 0 结果→SKIPPED / API 失败→重试 2 次→SKIPPED
    5. 全部失败→E3102 SearchFailed

    Returns:
        output dict（写入 step.output）
    """
    logger.info("Search stub: task_id=%s, step_id=%s", task.id, step.id)
    return {
        "status": "stub",
        "results": [],
        "total_results": 0,
        "after_dedup": 0,
        "message": "等待 §3.4 实现 Search 阶段",
    }
