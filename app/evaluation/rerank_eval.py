"""Rerank 阶段离线评估

从 EvidenceItem 的 relevance_score 计算均值、中位数、分布与高质量占比。
指标定义见 tests/TESTING_STRATEGY.md §11.2.3。
"""

from collections import Counter
from decimal import Decimal
from statistics import median

from app.evaluation.constants import HIGH_QUALITY_THRESHOLD, SCORE_BINS
from app.evaluation.models import RerankMetrics


def _bin_label(lower: Decimal, upper: Decimal, is_last: bool) -> str:
    """生成区间标签，例如 '[0.00,0.20)' 或 '[0.80,1.00]'。"""
    if is_last:
        return f"[{lower},{upper}]"
    return f"[{lower},{upper})"


def evaluate_rerank(evidence_items: list[dict] | None) -> RerankMetrics:
    """计算 Rerank 阶段的相关性指标。

    Args:
        evidence_items: EvidenceItem 列表，每个元素需包含 `relevance_score`。
            score 可以是 float、Decimal 或字符串表示的数字。

    Returns:
        RerankMetrics 对象。输入为空列表时返回零值指标。
    """
    if not evidence_items:
        return RerankMetrics()

    scores: list[Decimal] = []
    for item in evidence_items:
        if isinstance(item, dict):
            score = item.get("relevance_score", 0)
        else:
            score = getattr(item, "relevance_score", 0)
        if isinstance(score, Decimal):
            scores.append(score)
        else:
            scores.append(Decimal(str(score)))

    evidence_count = len(scores)
    min_score = float(min(scores))
    max_score = float(max(scores))
    mean_score = float(sum(scores) / evidence_count)
    median_score = float(median(scores))

    high_quality_count = sum(1 for s in scores if s >= HIGH_QUALITY_THRESHOLD)
    high_quality_ratio = high_quality_count / evidence_count if evidence_count else 0.0

    # 按 SCORE_BINS 分箱
    bins = SCORE_BINS
    distribution: Counter = Counter()
    for i in range(len(bins) - 1):
        lower = bins[i]
        upper = bins[i + 1]
        is_last = i == len(bins) - 2
        label = _bin_label(lower, upper, is_last)
        count = 0
        for s in scores:
            if is_last:
                if lower <= s <= upper:
                    count += 1
            else:
                if lower <= s < upper:
                    count += 1
        distribution[label] = count

    return RerankMetrics(
        evidence_count=evidence_count,
        mean_score=mean_score,
        median_score=median_score,
        min_score=min_score,
        max_score=max_score,
        high_quality_ratio=high_quality_ratio,
        score_distribution=dict(distribution),
    )
