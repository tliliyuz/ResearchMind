"""Evidence Graph Build 阶段 —— 结构化认知资产组装。

对齐 RESEARCH_PIPELINE.md §7：
- 纯程序化步骤，不调用 LLM
- 将 SynthesisNotes.clusters/conflicts/gaps 与 Rerank 产出的 Evidence
  组装为结构化的 Evidence Graph，供 Report Render 消费
- Graph 写入 research_steps.output（step_type='evidence_graph'）

Evidence 索引说明：
- Synthesis 阶段内部使用 0-based 索引（按 relevance_score 降序后的位置）
- Evidence Graph Build 同样按 relevance_score 降序取前 max_sources 条，
  重新分配 0-based index，因此 Synthesis 的 indices 可直接映射到 Graph items
"""

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import EvidenceGraphBuildFailedException
from app.models.evidence_item import EvidenceItem
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import SSEBridge, EVENT_STEP_PROGRESS

logger = logging.getLogger(__name__)

# ── 数据类型 ──────────────────────────────────────────────────


class GraphItem:
    """Evidence Graph 中的单条证据条目（内存结构）。"""

    def __init__(self, index: int, evidence_item: EvidenceItem):
        self.index = index
        self.evidence_item_id = evidence_item.id
        self.source_id = evidence_item.source_id
        self.source_url = ""
        self.source_title = ""
        self.domain = ""
        self.content = evidence_item.content or ""
        self.relevance_score = float(evidence_item.relevance_score or 0.0)
        self.cluster_theme = ""
        self.consensus_level = ""
        self.used_in_sections: list[str] = []

        source = evidence_item.source
        if source is not None:
            self.source_url = source.url or ""
            self.source_title = source.title or ""
            self.domain = source.domain or ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "evidence_item_id": self.evidence_item_id,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "domain": self.domain,
            "content": self.content,
            "relevance_score": self.relevance_score,
            "cluster_theme": self.cluster_theme,
            "consensus_level": self.consensus_level,
            "used_in_sections": self.used_in_sections,
        }


class GraphCluster:
    """Evidence Graph 中的聚类（内存结构）。"""

    def __init__(self, theme: str, summary: str, consensus_level: str, evidence_indices: list[int]):
        self.theme = theme
        self.summary = summary
        self.consensus_level = consensus_level
        self.evidence_indices = evidence_indices

    def to_dict(self) -> dict:
        return {
            "theme": self.theme,
            "summary": self.summary,
            "consensus_level": self.consensus_level,
            "evidence_indices": self.evidence_indices,
        }


# ── 工具函数 ──────────────────────────────────────────────────


def _to_str(value: Any, default: str = "") -> str:
    """安全转换为字符串。"""
    if isinstance(value, str):
        return value
    return default


def _to_list(value: Any) -> list:
    """安全转换为列表；非列表返回空列表。"""
    if isinstance(value, list):
        return value
    return []


def _filter_indices(indices: list[Any], item_count: int, field_name: str) -> list[int]:
    """过滤 evidence 索引：只保留整数且在有效范围内。

    - 非整数索引 → 静默跳过
    - 越界索引 → 静默跳过
    """
    valid: list[int] = []
    for idx in indices:
        if isinstance(idx, int) and 0 <= idx < item_count:
            valid.append(idx)
        else:
            logger.warning(
                "%s 越界或非整数索引被过滤: %r（有效范围 0-%d）",
                field_name, idx, item_count - 1,
            )
    return valid


# ── 上游数据读取 ──────────────────────────────────────────────


async def _load_synthesis_output(
    session: AsyncSession,
    task: ResearchTask,
) -> dict:
    """读取最新 completed Synthesis Step 的 output。"""
    stmt = (
        select(ResearchStep)
        .where(
            ResearchStep.task_id == task.id,
            ResearchStep.step_type == "synthesis",
            ResearchStep.status == "completed",
        )
        .order_by(ResearchStep.completed_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    step: ResearchStep | None = result.scalar_one_or_none()

    if step is None or step.output is None:
        raise EvidenceGraphBuildFailedException(detail="缺少已完成的 Synthesis Step 或其 output")

    if not isinstance(step.output, dict):
        raise EvidenceGraphBuildFailedException(detail="Synthesis Step output 格式异常，应为 JSON 对象")

    return step.output


async def _load_evidence_items(
    session: AsyncSession,
    task: ResearchTask,
) -> list[EvidenceItem]:
    """读取任务下的全部 EvidenceItem（含 source 关系），按 relevance_score 降序。"""
    stmt = (
        select(EvidenceItem)
        .where(EvidenceItem.task_id == task.id)
        .options(selectinload(EvidenceItem.source))
        .order_by(
            sa.case((EvidenceItem.relevance_score == None, 1), else_=0),
            EvidenceItem.relevance_score.desc(),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ── Graph 构建 ────────────────────────────────────────────────


def _build_graph_items(evidence_items: list[EvidenceItem], max_sources: int) -> list[GraphItem]:
    """取前 max_sources 条 Evidence，按排序后位置分配 0-based index。"""
    selected = evidence_items[:max_sources]
    return [GraphItem(index=i, evidence_item=ev) for i, ev in enumerate(selected)]


def _apply_clusters(items: list[GraphItem], clusters_raw: list[Any]) -> list[GraphCluster]:
    """应用 Synthesis clusters：写回 items 的 cluster_theme/consensus_level，生成 graph clusters。"""
    item_count = len(items)
    graph_clusters: list[GraphCluster] = []

    for i, c in enumerate(clusters_raw):
        if not isinstance(c, dict):
            logger.warning("clusters[%d] 不是对象，已跳过", i)
            continue

        theme = _to_str(c.get("theme"), "").strip()
        summary = _to_str(c.get("summary"), "").strip()
        consensus_level = _to_str(c.get("consensus_level"), "").strip()

        supporting = _filter_indices(
            _to_list(c.get("supporting_evidence_indices")),
            item_count,
            f"clusters[{i}].supporting_evidence_indices",
        )
        conflicting = _filter_indices(
            _to_list(c.get("conflicting_evidence_indices")),
            item_count,
            f"clusters[{i}].conflicting_evidence_indices",
        )

        # 先写回 supporting indices（主分类）
        for idx in supporting:
            items[idx].cluster_theme = theme
            items[idx].consensus_level = consensus_level

        # conflicting indices 作为 fallback：仅在未被 supporting 覆盖时写入
        for idx in conflicting:
            if not items[idx].cluster_theme:
                items[idx].cluster_theme = theme
                items[idx].consensus_level = consensus_level

        # evidence_indices = 去重排序后的合并列表
        merged = sorted(set(supporting + conflicting))
        graph_clusters.append(GraphCluster(
            theme=theme,
            summary=summary,
            consensus_level=consensus_level,
            evidence_indices=merged,
        ))

    return graph_clusters


def _build_conflicts(conflicts_raw: Any, item_count: int) -> list[dict]:
    """透传 conflicts，过滤越界/非整数索引。"""
    conflicts = _to_list(conflicts_raw)
    result: list[dict] = []
    for i, c in enumerate(conflicts):
        if not isinstance(c, dict):
            continue
        result.append({
            "topic": _to_str(c.get("topic"), ""),
            "position_a": _normalize_conflict_position(
                c.get("position_a"), item_count, f"conflicts[{i}].position_a"
            ),
            "position_b": _normalize_conflict_position(
                c.get("position_b"), item_count, f"conflicts[{i}].position_b"
            ),
        })
    return result


def _normalize_conflict_position(pos: Any, item_count: int, field_name: str) -> dict:
    """规范化 conflict position 结构，过滤越界/非整数索引。"""
    if not isinstance(pos, dict):
        return {"summary": "", "evidence_indices": []}
    indices = _filter_indices(
        _to_list(pos.get("evidence_indices")),
        item_count,
        field_name,
    )
    return {
        "summary": _to_str(pos.get("summary"), ""),
        "evidence_indices": indices,
    }


def _build_knowledge_gaps(gaps_raw: Any) -> list[str]:
    """透传 knowledge_gaps，过滤为空字符串。"""
    gaps = _to_list(gaps_raw)
    return [str(g).strip() for g in gaps if isinstance(g, str) and g.strip()]


def _aggregate_sources(items: list[GraphItem]) -> list[dict]:
    """按 source_id 聚合 evidence 贡献数。"""
    counts: dict[int, int] = {}
    source_meta: dict[int, GraphItem] = {}

    for item in items:
        counts[item.source_id] = counts.get(item.source_id, 0) + 1
        if item.source_id not in source_meta:
            source_meta[item.source_id] = item

    sources = []
    for source_id in counts:
        meta = source_meta[source_id]
        sources.append({
            "id": source_id,
            "url": meta.source_url,
            "title": meta.source_title,
            "domain": meta.domain,
            "evidence_count": counts[source_id],
        })

    # 按 evidence_count 降序、source_id 升序，保证顺序稳定
    sources.sort(key=lambda s: (-s["evidence_count"], s["id"]))
    return sources


# ── 主入口 ────────────────────────────────────────────────────


async def run_evidence_graph(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse: SSEBridge,
) -> dict:
    """执行 Evidence Graph Build 阶段。

    1. 读取 max_sources
    2. 读取 Synthesis output
    3. 读取 EvidenceItem 并按 relevance_score 降序
    4. 取前 max_sources 条构建 Graph items
    5. 应用 clusters，生成 graph clusters
    6. 透传 conflicts / knowledge_gaps
    7. 聚合 sources
    8. 发布 SSE step.progress 事件
    9. 返回 output dict（含完整 graph + 计数摘要）

    Returns:
        output dict（写入 step.output）
    """
    task_id = str(task.id)
    step_id = str(step.id)

    requirements = task.requirements or {}
    max_sources = int(requirements.get("max_sources", 10))

    logger.info("Evidence Graph Build 开始: task_id=%s, max_sources=%d", task_id, max_sources)

    await sse.publish(EVENT_STEP_PROGRESS, {
        "step_id": step_id,
        "phase": "building_evidence_graph",
        "label": "正在构建来源图谱...",
    })

    # 1. 读取 Synthesis output
    synthesis_output = await _load_synthesis_output(session, task)

    clusters_raw = synthesis_output.get("clusters")
    if not isinstance(clusters_raw, list):
        raise EvidenceGraphBuildFailedException(detail="Synthesis output 缺少有效的 clusters 数组")

    # 2. 读取 EvidenceItem
    evidence_items = await _load_evidence_items(session, task)
    if not evidence_items:
        raise EvidenceGraphBuildFailedException(detail="没有 EvidenceItem 可供构建 Evidence Graph")

    # 3. 构建 Graph items
    items = _build_graph_items(evidence_items, max_sources)

    # 4. 应用 clusters
    clusters = _apply_clusters(items, clusters_raw)

    # 5. 透传 conflicts / knowledge_gaps
    conflicts = _build_conflicts(synthesis_output.get("conflicts"), len(items))
    knowledge_gaps = _build_knowledge_gaps(synthesis_output.get("knowledge_gaps"))

    # 6. 聚合 sources
    sources = _aggregate_sources(items)

    # 7. 计算耗时
    duration_ms = 0
    if step.started_at:
        delta = datetime.now(timezone.utc) - step.started_at
        duration_ms = int(delta.total_seconds() * 1000)

    # 8. 发布进度事件
    await sse.publish(EVENT_STEP_PROGRESS, {
        "step_id": step_id,
        "phase": "building_evidence_graph",
        "label": f"来源图谱构建完成：{len(items)} 条来源，{len(clusters)} 个聚类",
        "item_count": len(items),
        "cluster_count": len(clusters),
        "source_count": len(sources),
    })

    # 9. 组装 Graph
    graph = {
        "task_id": task_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": [item.to_dict() for item in items],
        "clusters": [cluster.to_dict() for cluster in clusters],
        "conflicts": conflicts,
        "knowledge_gaps": knowledge_gaps,
        "sources": sources,
    }

    output = {
        "graph": graph,
        "item_count": len(items),
        "cluster_count": len(clusters),
        "conflict_count": len(conflicts),
        "source_count": len(sources),
        "duration_ms": duration_ms,
    }

    logger.info(
        "Evidence Graph Build 完成: task_id=%s, items=%d, clusters=%d, conflicts=%d, sources=%d",
        task_id, len(items), len(clusters), len(conflicts), len(sources),
    )

    return output
