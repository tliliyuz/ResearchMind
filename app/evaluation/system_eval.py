"""系统级可靠性评估

计算 Task Completion Rate 与 LLM Call Success Rate，均为跨任务聚合指标。
指标定义见 tests/TESTING_STRATEGY.md §11.3。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.constants import TARGETS
from app.evaluation.loader import load_llm_step_status_counts, load_task_terminal_status_counts
from app.evaluation.models import SystemReliabilityMetrics


async def evaluate_system_reliability(
    session: AsyncSession,
    targets: dict[str, float] | None = None,
) -> SystemReliabilityMetrics:
    """计算系统级可靠性指标（Task Completion Rate + LLM Call Success Rate）。

    Args:
        session: 异步数据库会话。
        targets: 自定义目标值字典，默认使用 constants.TARGETS。

    Returns:
        SystemReliabilityMetrics 对象。
    """
    task_counts = await load_task_terminal_status_counts(session)
    llm_counts = await load_llm_step_status_counts(session)

    task_success = task_counts["completed"] + task_counts["partially_completed"]
    task_total = (
        task_counts["completed"]
        + task_counts["partially_completed"]
        + task_counts["failed"]
        + task_counts["canceled"]
    )
    task_completion_rate = task_success / task_total if task_total > 0 else 0.0

    llm_completed = llm_counts["completed"]
    llm_total = llm_completed + llm_counts["failed"]
    llm_call_success_rate = llm_completed / llm_total if llm_total > 0 else 0.0

    return SystemReliabilityMetrics(
        task_completed=task_counts["completed"],
        task_partially_completed=task_counts["partially_completed"],
        task_failed=task_counts["failed"],
        task_canceled=task_counts["canceled"],
        task_completion_rate=task_completion_rate,
        llm_calls_completed=llm_completed,
        llm_calls_failed=llm_counts["failed"],
        llm_call_success_rate=llm_call_success_rate,
    )


def check_system_targets(
    metrics: SystemReliabilityMetrics,
    targets: dict[str, float] | None = None,
) -> dict[str, bool]:
    """将系统可靠性指标与目标值对比。

    Args:
        metrics: 系统可靠性指标。
        targets: 目标值字典，默认 TARGETS。

    Returns:
        各指标达标情况字典，key 与 TARGETS 中的 key 对应。
    """
    effective = dict(targets if targets is not None else TARGETS)
    return {
        "task_completion_rate": metrics.task_completion_rate > effective.get("task_completion_rate", 0.0),
        "llm_call_success_rate": metrics.llm_call_success_rate > effective.get("llm_call_success_rate", 0.0),
    }
