"""RRF 多路融合排序 — Reciprocal Rank Fusion

对齐 RESEARCH_PIPELINE.md §5.2（二段式 Rerank 架构）：
- score(d) = Σ 1 / (k + rank_i(d))，k=60
- 单路为空时仅返回另一路结果
- 支持多路检索结果融合（v1.5 SearXNG + Tavily 双路搜索）

适配 ResearchMind 自有类型 SearchResult/SearchOutput。
"""

import logging
from collections import defaultdict

from app.pipeline.types import SearchOutput, SearchResult

logger = logging.getLogger(__name__)

# RRF 平滑常数（k=60 为信息检索领域标准值）
RRF_K = 60


def rrf_fusion(
    *search_outputs: SearchOutput,
    k: int = RRF_K,
) -> SearchOutput:
    """多路检索结果的 RRF 融合排序。

    - score(d) = Σ 1 / (k + rank_i(d))
    - 单路为空时仅返回另一路结果
    - 两路均空时返回空结果

    Args:
        *search_outputs: 多路检索结果（可变参数，如 Tavily + SearXNG）
        k: RRF 平滑常数，默认 60

    Returns:
        SearchOutput: 融合后的结果，按 RRF 分数降序排列
    """
    if not search_outputs:
        logger.warning("未提供任何检索结果")
        return SearchOutput()

    # 过滤空结果
    non_empty_outputs = [output for output in search_outputs if output.results]

    # 所有路均为空
    if not non_empty_outputs:
        logger.info("所有检索路均为空结果")
        return SearchOutput()

    # 单路非空：直接返回该路结果
    if len(non_empty_outputs) == 1:
        logger.info("仅单路有结果，直接返回")
        output = non_empty_outputs[0]
        output.fusion_method = "rrf"
        return output

    # 多路非空：执行 RRF 融合
    return _do_rrf_fusion(non_empty_outputs, k)


def _do_rrf_fusion(
    outputs: list[SearchOutput],
    k: int,
) -> SearchOutput:
    """执行 RRF 融合算法。

    Args:
        outputs: 非空的检索结果列表
        k: RRF 平滑常数

    Returns:
        SearchOutput: 融合后的结果
    """
    # 用于聚合每个结果的 RRF 分数和最佳结果
    # key: source_id → {"score": float, "result": SearchResult}
    result_scores: dict[int, dict] = defaultdict(lambda: {"score": 0.0, "result": None})

    for output in outputs:
        for rank, result in enumerate(output.results, start=1):
            source_key = result.source_id

            # RRF 分数累加：1 / (k + rank)
            rrf_contribution = 1.0 / (k + rank)
            result_scores[source_key]["score"] += rrf_contribution

            # 保留最佳结果（优先保留有内容的）
            if result_scores[source_key]["result"] is None:
                result_scores[source_key]["result"] = result

    # 按 RRF 分数降序排列
    sorted_results = sorted(
        result_scores.items(),
        key=lambda item: item[1]["score"],
        reverse=True,
    )

    # 构建融合结果
    results: list[SearchResult] = []
    for source_key, data in sorted_results:
        original = data["result"]
        fused_result = SearchResult(
            source_id=original.source_id,
            content=original.content,
            score=data["score"],
            url=original.url,
            title=original.title,
            matched_sentence=original.matched_sentence,
            matched_sentence_score=original.matched_sentence_score,
        )
        results.append(fused_result)

    logger.info(
        "RRF 融合完成: %d 路输入, %d 条融合结果 (k=%d)",
        len(outputs), len(results), k,
    )

    return SearchOutput(results=results, total=len(results), fusion_method="rrf")
