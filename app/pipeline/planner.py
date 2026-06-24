"""Planning 阶段 —— 研究主题拆解为 SubQuestion[]。

§3.3 实现完整逻辑（LLM 调用 + 输出校验 + task_type 策略注入）。
当前为最小 stub，Pipeline Orchestrator 可调通全链路。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep

logger = logging.getLogger(__name__)


async def run_planning(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge,  # SSEBridge
) -> dict:
    """执行 Planning 阶段（stub）。

    §3.3 将替换为：
    1. 构建 Planning System Prompt（含 task_type 策略注入）
    2. 调用 deepseek-v4-pro（deep_thinking=True, temperature=0.3）
    3. Pydantic 校验输出（3-5 SubQuestions, ≤200 字符, ≥2 实体）
    4. 不满足 → 重试（最多 3 次）
    5. 仍失败 → E3101 PlanningFailed

    Returns:
        output dict（写入 step.output）
    """
    logger.info("Planning stub: task_id=%s, step_id=%s", task.id, step.id)
    return {
        "status": "stub",
        "sub_questions": [],
        "message": "等待 §3.3 实现 Planning 阶段",
    }
