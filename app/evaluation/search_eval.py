"""Search 阶段离线评估

从 Search Step 的 output 中提取 sub_question_results，计算 Coverage Rate 与 Recall@K。
指标定义见 tests/TESTING_STRATEGY.md §11.2.1。
"""

from app.evaluation.constants import SEARCH_RECALL_K
from app.evaluation.models import SearchMetrics


def evaluate_search(search_output: dict | None, k: int = SEARCH_RECALL_K) -> SearchMetrics:
    """计算 Search 阶段的 Coverage Rate 与 Recall@K。

    Args:
        search_output: `ResearchStep.output`（step_type='search'），含
            `sub_question_results` 列表。每个元素需包含 `results_count`。
        k: Recall@K 的 K 值，默认 5。

    Returns:
        SearchMetrics 对象。输入为空或无任何子问题时返回零值指标。
    """
    if not search_output:
        return SearchMetrics(k=k)

    sub_results = search_output.get("sub_question_results") or []
    if not sub_results:
        return SearchMetrics(k=k)

    sub_question_count = len(sub_results)
    total_results = 0
    covered_count = 0
    recall_sum = 0.0

    for item in sub_results:
        results_count = int(item.get("results_count", 0) or 0)
        total_results += results_count
        if results_count > 0:
            covered_count += 1
        recall_sum += min(results_count, k) / k

    coverage_rate = covered_count / sub_question_count if sub_question_count else 0.0
    recall_at_k = recall_sum / sub_question_count if sub_question_count else 0.0
    avg_results = total_results / sub_question_count if sub_question_count else 0.0

    return SearchMetrics(
        sub_question_count=sub_question_count,
        total_results=total_results,
        avg_results_per_sub_question=avg_results,
        coverage_rate=coverage_rate,
        recall_at_k=recall_at_k,
        k=k,
    )
