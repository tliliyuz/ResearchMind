"""Fetch 阶段 —— 网页内容抓取 + trafilatura 正文提取 + 安全校验。

§3.5 实现完整逻辑（HTTP GET + SSRF 防护 + 内容截断）。
当前为最小 stub，Pipeline Orchestrator 可调通全链路。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep

logger = logging.getLogger(__name__)


async def run_fetch(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge,  # SSEBridge
) -> dict:
    """执行 Fetch 阶段（stub）。

    §3.5 将替换为：
    1. 读取 Search 阶段产出的去重 URL 列表
    2. 对每个 URL：
       a. 安全检查（协议白名单 http/https + IP 黑名单 SSRF 防护）
       b. HTTP GET（timeout=15s, User-Agent: ResearchMind/1.0）
       c. trafilatura 正文提取
       d. 内容截断（100KB）
    3. 失败策略：超时重试 1 次 / 403/404/DNS→直接 SKIPPED
    4. 写入 research_sources 表

    Returns:
        output dict（写入 step.output）
    """
    logger.info("Fetch stub: task_id=%s, step_id=%s", task.id, step.id)
    return {
        "status": "stub",
        "fetched": [],
        "successful": 0,
        "failed": 0,
        "message": "等待 §3.5 实现 Fetch 阶段",
    }
