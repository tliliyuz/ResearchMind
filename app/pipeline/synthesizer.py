"""Synthesis 阶段 —— 跨源综合。

对齐 RESEARCH_PIPELINE.md §6：
- 读取 Rerank 产出的 Evidence[]
- 调用 deepseek-v4-pro（deep_thinking=True, temperature=0.3, max_tokens=5000）
- 完成观点聚类 / 共识识别 / 冲突发现 / 信息缺口
- 输出 SynthesisNotes 写入 research_steps.output，供 Evidence Graph Build 消费

Evidence 索引说明：
- 本阶段内部使用 0-based 索引（对齐 §6.2 示例 [0,3,7]）
- §6.3 Evidence 格式化策略中的「[来源 N]」在内部被转换为 0-based 索引
- 最终 SynthesisNotes.clusters[i].supporting_evidence_indices 保持 0-based
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import SynthesisFailedException
from app.core.llm import LLMResult, chat_completion
from app.models.evidence_item import EvidenceItem
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_PROGRESS,
)

logger = logging.getLogger(__name__)

# ── System Prompt 模板（对齐 RESEARCH_PIPELINE.md §6.2）────────

_SYSTEM_PROMPT_TEMPLATE = """你是一个研究综合专家。请基于以下研究证据进行跨源综合。

研究主题：{topic}
研究类型：{task_type}

研究证据（共 {evidence_count} 条）：
{evidence_items_formatted}

请完成以下任务：

1. **观点聚类**：将证据按观点/结论分组，每组标注核心主题
2. **共识识别**：标记多个来源共同支持的高置信度结论
3. **冲突发现**：标注不同来源之间的矛盾或分歧
4. **信息缺口**：指出研究主题中未被证据覆盖的方面

输出严格 JSON 格式：
{{
  "clusters": [
    {{
      "theme": "聚类主题",
      "summary": "该聚类的核心结论（1-2 句）",
      "consensus_level": "strong" | "moderate" | "weak",
      "supporting_evidence_indices": [0, 3, 7],
      "conflicting_evidence_indices": []
    }}
  ],
  "conflicts": [
    {{
      "topic": "分歧主题",
      "position_a": {{"summary": "...", "evidence_indices": [1]}},
      "position_b": {{"summary": "...", "evidence_indices": [4]}}
    }}
  ],
  "knowledge_gaps": ["未被充分覆盖的方面 1", ...],
  "overall_assessment": "整体证据质量评估（2-3 句）"
}}"""

# ── 数据类型 ──────────────────────────────────────────────────


@dataclass
class ConflictPosition:
    """冲突中的一方立场。"""
    summary: str
    evidence_indices: list[int]


@dataclass
class SynthesisCluster:
    """观点聚类。"""
    theme: str
    summary: str
    consensus_level: str  # strong / moderate / weak
    supporting_evidence_indices: list[int]
    conflicting_evidence_indices: list[int]


@dataclass
class SynthesisConflict:
    """冲突发现。"""
    topic: str
    position_a: ConflictPosition
    position_b: ConflictPosition


@dataclass
class SynthesisNotes:
    """Synthesis 阶段最终输出。"""
    clusters: list[SynthesisCluster]
    conflicts: list[SynthesisConflict]
    knowledge_gaps: list[str]
    overall_assessment: str


# ── 工具函数 ──────────────────────────────────────────────────


def _extract_json_from_text(text: str) -> str:
    """从 LLM 输出中提取 JSON（处理可能的 markdown 代码块包装）。"""
    text = text.strip()

    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block_match:
        return code_block_match.group(1).strip()

    brace_start = text.find("{")
    if brace_start == -1:
        return text

    brace_end = text.rfind("}")
    if brace_end == -1:
        return text

    return text[brace_start:brace_end + 1]


def _format_evidence_items(items: list[EvidenceItem], max_sources: int) -> tuple[str, list[EvidenceItem]]:
    """将 EvidenceItem[] 格式化为 Prompt 文本。

    处理逻辑：
    1. 按 relevance_score 降序（防御性重排）
    2. 取前 K = min(max_sources, len) 条
    3. 单条内容截断至 1500 字符
    4. 使用 0-based 索引 [来源 0], [来源 1]...

    Returns:
        (formatted_text, selected_items)
    """
    sorted_items = sorted(
        items,
        key=lambda e: e.relevance_score or 0.0,
        reverse=True,
    )
    selected = sorted_items[:min(max_sources, len(sorted_items))]

    parts: list[str] = []
    for i, ev in enumerate(selected, start=0):
        source = ev.source
        domain = source.domain if source else "unknown"
        title = source.title if source else "无标题"
        content = ev.content[:1500] if ev.content else ""
        parts.append(
            f"来源标注：[来源 {i}] {domain} — {title}\n内容：{content}"
        )

    return "\n\n".join(parts), selected


def _build_synthesis_prompt(
    topic: str,
    task_type: str,
    evidence_items_formatted: str,
    evidence_count: int,
) -> list[dict[str, str]]:
    """构建 Synthesis Prompt。"""
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        topic=topic,
        task_type=task_type,
        evidence_count=evidence_count,
        evidence_items_formatted=evidence_items_formatted,
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请基于上述研究证据进行跨源综合，输出严格 JSON 格式。"},
    ]


def _validate_indices(indices: list[Any], expected_count: int, field_name: str) -> list[int]:
    """校验 evidence 索引列表。

    - 非整数索引 → raise ValueError（触发重试）
    - 越界索引 → 过滤并记录 warning（不触发重试）

    Returns:
        过滤后的合法 int 索引列表
    """
    valid: list[int] = []
    for idx in indices:
        if not isinstance(idx, int):
            raise ValueError(f"{field_name} 包含非整数索引: {idx!r}")
        if 0 <= idx < expected_count:
            valid.append(idx)
        else:
            logger.warning("%s 越界索引被过滤: %d（有效范围 0-%d）", field_name, idx, expected_count - 1)
    return valid


def _parse_synthesis_output(raw_text: str, expected_count: int) -> SynthesisNotes:
    """解析 LLM 输出为 SynthesisNotes。

    Raises:
        ValueError: JSON 无效、clusters 缺失/格式错误、索引非整数
    """
    json_text = _extract_json_from_text(raw_text)
    data = json.loads(json_text)

    if not isinstance(data, dict):
        raise ValueError("LLM 输出不是 JSON 对象")

    # clusters 必须存在且为数组
    clusters_raw = data.get("clusters")
    if not isinstance(clusters_raw, list):
        raise ValueError("缺少 clusters 数组")

    clusters: list[SynthesisCluster] = []
    for i, c in enumerate(clusters_raw):
        if not isinstance(c, dict):
            raise ValueError(f"clusters[{i}] 不是对象")

        theme = c.get("theme", "")
        summary = c.get("summary", "")
        if not isinstance(theme, str) or not theme.strip():
            raise ValueError(f"clusters[{i}].theme 为空")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"clusters[{i}].summary 为空")

        consensus_level = c.get("consensus_level", "")
        if consensus_level not in {"strong", "moderate", "weak"}:
            raise ValueError(f"clusters[{i}].consensus_level 非法: {consensus_level}")

        supporting = _validate_indices(
            c.get("supporting_evidence_indices", []) or [],
            expected_count,
            f"clusters[{i}].supporting_evidence_indices",
        )
        conflicting = _validate_indices(
            c.get("conflicting_evidence_indices", []) or [],
            expected_count,
            f"clusters[{i}].conflicting_evidence_indices",
        )

        clusters.append(SynthesisCluster(
            theme=theme.strip(),
            summary=summary.strip(),
            consensus_level=consensus_level,
            supporting_evidence_indices=supporting,
            conflicting_evidence_indices=conflicting,
        ))

    # conflicts 允许 null → 空数组
    conflicts_raw = data.get("conflicts")
    if conflicts_raw is None:
        conflicts_raw = []
    if not isinstance(conflicts_raw, list):
        raise ValueError("conflicts 必须是数组或 null")

    conflicts: list[SynthesisConflict] = []
    for i, c in enumerate(conflicts_raw):
        if not isinstance(c, dict):
            raise ValueError(f"conflicts[{i}] 不是对象")

        topic = c.get("topic", "")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError(f"conflicts[{i}].topic 为空")

        pos_a_raw = c.get("position_a", {})
        pos_b_raw = c.get("position_b", {})
        if not isinstance(pos_a_raw, dict) or not isinstance(pos_b_raw, dict):
            raise ValueError(f"conflicts[{i}] position 不是对象")

        pos_a = ConflictPosition(
            summary=str(pos_a_raw.get("summary", "")).strip(),
            evidence_indices=_validate_indices(
                pos_a_raw.get("evidence_indices", []) or [],
                expected_count,
                f"conflicts[{i}].position_a.evidence_indices",
            ),
        )
        pos_b = ConflictPosition(
            summary=str(pos_b_raw.get("summary", "")).strip(),
            evidence_indices=_validate_indices(
                pos_b_raw.get("evidence_indices", []) or [],
                expected_count,
                f"conflicts[{i}].position_b.evidence_indices",
            ),
        )

        conflicts.append(SynthesisConflict(
            topic=topic.strip(),
            position_a=pos_a,
            position_b=pos_b,
        ))

    # knowledge_gaps 允许空数组
    gaps_raw = data.get("knowledge_gaps", [])
    if not isinstance(gaps_raw, list):
        raise ValueError("knowledge_gaps 必须是数组")
    knowledge_gaps = [str(g).strip() for g in gaps_raw if isinstance(g, str) and g.strip()]

    # overall_assessment 必须是非空字符串
    overall = data.get("overall_assessment", "")
    if not isinstance(overall, str) or not overall.strip():
        raise ValueError("overall_assessment 为空")

    return SynthesisNotes(
        clusters=clusters,
        conflicts=conflicts,
        knowledge_gaps=knowledge_gaps,
        overall_assessment=overall.strip(),
    )


# ── 上游数据读取 ──────────────────────────────────────────────


async def _load_evidence(
    session: AsyncSession,
    task: ResearchTask,
) -> list[EvidenceItem]:
    """读取 Rerank 产出的 EvidenceItem[]（含 source 关系）。"""
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


# ── LLM 综合 ──────────────────────────────────────────────────


async def _llm_synthesize(
    topic: str,
    task_type: str,
    evidence_items_formatted: str,
    evidence_count: int,
) -> tuple[SynthesisNotes, int, int, int]:
    """调用 LLM 完成跨源综合。

    Returns:
        (notes, prompt_tokens, completion_tokens, retry_count)

    Raises:
        SynthesisFailedException: 重试耗尽或输出无效
    """
    messages = _build_synthesis_prompt(
        topic=topic,
        task_type=task_type,
        evidence_items_formatted=evidence_items_formatted,
        evidence_count=evidence_count,
    )

    total_prompt_tokens = 0
    total_completion_tokens = 0
    last_error: Exception | None = None
    result: LLMResult | None = None

    for attempt in range(1, settings.PIPELINE_SYNTHESIS_MAX_RETRIES + 1):
        try:
            result = await chat_completion(
                messages=messages,
                model=settings.LLM_MODEL,
                deep_thinking=True,
                temperature=0.3,
                max_tokens=5000,
            )

            total_prompt_tokens += result.prompt_tokens
            total_completion_tokens += result.completion_tokens

            notes = _parse_synthesis_output(result.content, evidence_count)
            return notes, total_prompt_tokens, total_completion_tokens, attempt - 1

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning("Synthesis LLM 输出解析失败 (attempt %d): %s", attempt, e)
            if attempt < settings.PIPELINE_SYNTHESIS_MAX_RETRIES:
                messages.append({"role": "assistant", "content": result.content if result else ""})
                messages.append({
                    "role": "user",
                    "content": f"输出格式错误：{e}。请重新输出严格 JSON，确保 clusters 格式正确。",
                })
                continue
            break

        except Exception as e:
            last_error = e
            logger.warning("Synthesis LLM 调用失败 (attempt %d): %s", attempt, e)
            if attempt < settings.PIPELINE_SYNTHESIS_MAX_RETRIES:
                continue
            break

    raise SynthesisFailedException(
        detail=f"LLM Synthesis 失败（{settings.PIPELINE_SYNTHESIS_MAX_RETRIES} 次重试耗尽）: {last_error}"
    )


# ── 序列化辅助 ────────────────────────────────────────────────


def _cluster_to_dict(cluster: SynthesisCluster) -> dict:
    return {
        "theme": cluster.theme,
        "summary": cluster.summary,
        "consensus_level": cluster.consensus_level,
        "supporting_evidence_indices": cluster.supporting_evidence_indices,
        "conflicting_evidence_indices": cluster.conflicting_evidence_indices,
    }


def _conflict_to_dict(conflict: SynthesisConflict) -> dict:
    return {
        "topic": conflict.topic,
        "position_a": {
            "summary": conflict.position_a.summary,
            "evidence_indices": conflict.position_a.evidence_indices,
        },
        "position_b": {
            "summary": conflict.position_b.summary,
            "evidence_indices": conflict.position_b.evidence_indices,
        },
    }


# ── 主入口 ────────────────────────────────────────────────────


async def run_synthesis(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge: SSEBridge,
) -> dict:
    """执行 Synthesis 阶段。

    1. 读取 EvidenceItem[]
    2. 按 relevance_score 降序 + max_sources 截断
    3. 调用 LLM 完成跨源综合
    4. 发射 SSE 事件
    5. 返回 output dict（写入 step.output）

    Returns:
        output dict（含 clusters / conflicts / knowledge_gaps / overall_assessment）
    """
    task_id = str(task.id)
    step_id = str(step.id)

    requirements = task.requirements or {}
    task_type = requirements.get("task_type", "explainer")
    max_sources = int(requirements.get("max_sources", 10))

    logger.info("Synthesis 开始: task_id=%s, task_type=%s, max_sources=%d", task_id, task_type, max_sources)

    # 1. 读取上游 Evidence
    evidence_items = await _load_evidence(session, task)
    if not evidence_items:
        raise SynthesisFailedException(detail="没有可供综合的证据")

    # 2. 格式化 Evidence（0-based 索引）
    evidence_items_formatted, selected_items = _format_evidence_items(
        evidence_items,
        max_sources=max_sources,
    )
    evidence_count = len(selected_items)

    logger.info(
        "Synthesis Evidence 准备完成: task_id=%s, total=%d, selected=%d",
        task_id, len(evidence_items), evidence_count,
    )

    # 3. 调用 LLM 综合
    notes, prompt_tokens, completion_tokens, retry_count = await _llm_synthesize(
        topic=task.topic,
        task_type=task_type,
        evidence_items_formatted=evidence_items_formatted,
        evidence_count=evidence_count,
    )

    # 4. 进度事件（聚类完成）
    sse_bridge.publish(EVENT_STEP_PROGRESS, {
        "step_id": step_id,
        "phase": "synthesizing",
        "clusters_count": len(notes.clusters),
    })

    # 5. 完成事件
    sse_bridge.publish(EVENT_STEP_COMPLETED, {
        "step_id": step_id,
        "clusters": [_cluster_to_dict(c) for c in notes.clusters],
        "conflicts": [_conflict_to_dict(c) for c in notes.conflicts],
        "clusters_count": len(notes.clusters),
        "conflicts_count": len(notes.conflicts),
        "gaps_count": len(notes.knowledge_gaps),
    })

    output = {
        "clusters": [_cluster_to_dict(c) for c in notes.clusters],
        "conflicts": [_conflict_to_dict(c) for c in notes.conflicts],
        "knowledge_gaps": notes.knowledge_gaps,
        "overall_assessment": notes.overall_assessment,
        "clusters_count": len(notes.clusters),
        "conflicts_count": len(notes.conflicts),
        "gaps_count": len(notes.knowledge_gaps),
        "model": settings.LLM_MODEL,
        "retry_count": retry_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "evidence_count": evidence_count,
    }

    logger.info(
        "Synthesis 完成: task_id=%s, clusters=%d, conflicts=%d, gaps=%d, retries=%d",
        task_id, len(notes.clusters), len(notes.conflicts), len(notes.knowledge_gaps), retry_count,
    )

    return output
