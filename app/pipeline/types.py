"""Pipeline 通用数据类型 — 多路搜索融合 + 句级匹配 + 证据审计共用

对齐 RESEARCH_PIPELINE.md §5.5（Evidence 数据结构）+ §5.2（二段式 Rerank 架构）：
- SearchResult：标准化检索结果，BM25 / Tavily / SearXNG 多路共用
- SearchOutput：检索输出聚合，支持 RRF 融合
"""

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """标准化检索结果，多路搜索源共用。

    适配 ResearchMind 的 web 搜索场景：
    - 无 doc_id / chunk_index（ResearchMind 无文档库概念）
    - source_id 指向 research_sources.id
    - matched_sentence / matched_sentence_score 由 sentence_matcher 填充
    """
    source_id: int                      # 来源 ID（对应 research_sources.id）
    content: str                        # 内容文本
    score: float                        # 相关性分数
    url: str = ""                       # 来源 URL
    title: str = ""                     # 来源标题
    matched_sentence: str | None = None           # 最佳匹配句（句级 BM25 定位结果）
    matched_sentence_score: float | None = None   # 最佳匹配句 BM25 分数


@dataclass
class SearchOutput:
    """检索输出聚合，多路搜索融合的输入/输出类型。

    不含 stats（KB 检索性能统计）和 doc_name/section_title 等文档库特有字段。
    """
    results: list[SearchResult] = field(default_factory=list)
    total: int = 0
    fusion_method: str | None = None    # 融合算法名称（如 "rrf"），由 fusion.py 设置
