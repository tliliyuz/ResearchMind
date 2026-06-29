"""Fetch 阶段离线评估

从 Fetch Step 的 output 中提取每个 URL 的抓取状态，计算 Fetch Success Rate。
安全拦截 URL 单独统计，不计入分母。指标定义见 tests/TESTING_STRATEGY.md §11.2.2。
"""

from collections import Counter

from app.evaluation.models import FetchMetrics

FETCH_SUCCESS_STATUS = "success"
FETCH_FAILED_STATUSES = {"timeout", "blocked", "empty", "dns_error"}
FETCH_SAFETY_STATUS = "safety_blocked"


def evaluate_fetch(fetch_output: dict | None) -> FetchMetrics:
    """计算 Fetch 阶段的成功率与状态分布。

    Args:
        fetch_output: `ResearchStep.output`（step_type='fetch'），含 `fetched` 列表。
            每个元素需包含 `status`，可选值为 success / timeout / blocked / empty /
            dns_error / safety_blocked。

    Returns:
        FetchMetrics 对象。输入为空或无任何 URL 时返回零值指标。
    """
    if not fetch_output:
        return FetchMetrics()

    fetched = fetch_output.get("fetched") or []
    if not fetched:
        return FetchMetrics()

    status_distribution: Counter = Counter()
    successful = 0
    failed = 0
    skipped_safety = 0

    for item in fetched:
        status = item.get("status") or "unknown"
        status_distribution[status] += 1
        if status == FETCH_SUCCESS_STATUS:
            successful += 1
        elif status in FETCH_FAILED_STATUSES:
            failed += 1
        elif status == FETCH_SAFETY_STATUS:
            skipped_safety += 1

    total_attempted = successful + failed
    success_rate = successful / total_attempted if total_attempted else 0.0

    return FetchMetrics(
        successful=successful,
        failed=failed,
        skipped_safety=skipped_safety,
        success_rate=success_rate,
        status_distribution=dict(status_distribution),
    )
