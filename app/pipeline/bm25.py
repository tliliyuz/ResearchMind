"""BM25 关键词检索器 — 轻量版（纯内存计算，~60 行）

对齐 INFRASTRUCTURE_REUSE.md §4.1：
- 轻量版（纯内存计算，~60 行），不含 Redis L1/L2 缓存 + MySQL 懒加载 + 章节 boost
- ResearchMind 场景：15 篇文档 × 段落切分 ≈ 最多 45 候选，纯内存计算即可
- 仅保留核心：BM25Okapi + jieba.lcut

对齐 RESEARCH_PIPELINE.md §5.3 Rerank Stage 1：
- 每篇文档按 \\n\\n 段落切分（≤2000 字符/段）
- jieba 分词 → BM25Okapi 对每个 sub_question 评分
- 每文档取 top-3 段落 → 最多 45 候选
"""

import jieba
from rank_bm25 import BM25Okapi

from app.config import settings


def segment_document(content: str, max_chars: int | None = None) -> list[str]:
    """将文档按 \\n\\n 段落切分，每段不超过 max_chars 字符。

    Args:
        content: 文档正文内容
        max_chars: 每段最大字符数（None 时使用 RERANK_BM25_SEGMENT_MAX_CHARS）

    Returns:
        段落文本列表
    """
    limit = max_chars or settings.RERANK_BM25_SEGMENT_MAX_CHARS
    paragraphs = content.split("\n\n")
    segments = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 长段落截断为多段
        while len(para) > limit:
            segments.append(para[:limit])
            para = para[limit:]
        if para:
            segments.append(para)
    return segments


def bm25_rerank(
    segments: list[str],
    query: str,
    top_k: int | None = None,
) -> list[tuple[int, float]]:
    """对段落进行 BM25 评分，返回 top-K 的 (段落索引, 分数) 列表。

    Args:
        segments: 段落文本列表
        query: 查询文本（sub_question）
        top_k: 返回前 K 个结果（None 时使用 RERANK_BM25_TOP_K_PER_DOC）

    Returns:
        [(段落索引, BM25 分数), ...]，按分数降序排列
    """
    if not segments:
        return []

    k = top_k or settings.RERANK_BM25_TOP_K_PER_DOC

    # jieba 分词
    tokenized_segments = [jieba.lcut(seg) for seg in segments]
    tokenized_query = jieba.lcut(query)

    # BM25Okapi 评分
    bm25 = BM25Okapi(tokenized_segments)
    scores = bm25.get_scores(tokenized_query)

    # 按分数降序取 top-K
    indexed_scores = list(enumerate(scores))
    indexed_scores.sort(key=lambda x: x[1], reverse=True)

    return indexed_scores[:k]
