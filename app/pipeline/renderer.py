"""Report Render 阶段 —— 将 Evidence Graph 渲染为 Markdown 报告。

对齐 RESEARCH_PIPELINE.md §8：
- 读取 Evidence Graph（0-based index）
- 按 task_type 选择模板
- 调用 deepseek-v4-pro（deep_thinking=False, temperature=0.5, max_tokens=8000）
- 正文中使用 [来源N] 标注引用，N 即 GraphItem.index
- 解析并持久化 report_sections / section_evidence
- 更新 evidence_items.used_in_sections

引用锚点说明：
- 正文中 [来源N] 的 N 使用 0-based GraphItem.index（对齐 API.md §3.3）
- section.sources[].id = research_sources.id
- section.sources[].evidence_index = GraphItem.index
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import RenderFailedException
from app.core.llm import LLMResult, chat_completion
from app.core.token_counter import estimate_tokens
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.section_evidence import SectionEvidence
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_PROGRESS,
)

logger = logging.getLogger(__name__)

# ── System Prompt 模板（对齐 RESEARCH_PIPELINE.md §8.3）────────

_SYSTEM_PROMPT_TEMPLATE = """你是一个专业研究报告撰写专家。请基于以下研究证据图谱撰写报告。

研究主题：{topic}
研究类型：{task_type}
报告语言：{language}
报告模板：{template}
模板章节组织：{template_sections_description}

证据图谱：
- 证据条目：{item_count} 条
- 观点聚类：{clusters_summary}
- 已知冲突：{conflicts_summary}
- 知识缺口：{knowledge_gaps}

证据详情：
{evidence_items_formatted}

写作要求：
1. 每个 Section 的内容必须基于提供的证据，不得编造
2. 每个事实性陈述必须标注来源引用：`[来源N]`，其中 N 是证据详情中的 0-based 编号。注意：必须是独立的 `[来源N]`，不要写成 `[来源N,M]`、`[来源 N]` 或 `[来源N-M]`，N 从 0 开始计数
3. Section 末尾列出该节使用的所有来源索引（格式：`[来源N]`，N 为 0-based 编号）
4. 使用 Markdown 格式，包含标题层级、列表、表格（如需要）
5. 承认知识缺口——不要为了报告「完整」而编造内容

输出格式：
{sections_json_schema}

注意：必须输出合法 JSON，不要包含任何 JSON 之外的解释文字。"""

# ── 模板描述（对齐 RESEARCH_PIPELINE.md §8.2）───────────────────

_TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "comparison": (
        "1. 概述 → 2. 候选对象简介 → 3. 对比维度矩阵 → "
        "4. 逐维度深度分析 → 5. 总结与建议"
    ),
    "explainer": (
        "1. 背景介绍 → 2-N. 按研究方向/证据聚类组织章节 → "
        "N+1. 争议与前沿 → 最后. 总结"
    ),
    "analysis": (
        "1. 现状概述 → 2. 威胁/原因分析 → 3. 影响推演 → "
        "4. 应对策略 → 5. 时间线预估"
    ),
}

# ── 数据类型 ──────────────────────────────────────────────────


@dataclass
class RenderSection:
    """Render 阶段解析出的单个报告章节。"""

    heading: str
    content: str
    sources: list[dict]  # [{"id": source_id, "evidence_index": index}, ...]


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

    return text[brace_start : brace_end + 1]


def _select_template(task_type: str) -> tuple[str, str]:
    """选择报告模板，返回 (template_name, template_sections_description)。"""
    normalized = task_type if task_type in _TEMPLATE_DESCRIPTIONS else "explainer"
    template_name = f"{normalized}_v1"
    return template_name, _TEMPLATE_DESCRIPTIONS[normalized]


def _format_evidence_items(items: list[dict]) -> str:
    """把 Graph items 格式化为 Prompt 文本，受 TOKEN_BUDGET_SOFT_LIMIT 约束。

    策略：按原始顺序尝试截断单条内容长度，再减少条目数，确保 Prompt
    不超过软上限。
    """
    valid_items = [
        item for item in items
        if isinstance(item, dict) and item.get("index") is not None
    ]

    content_limit = 1500
    count_limit = len(valid_items)
    while count_limit >= 1:
        parts: list[str] = []
        for item in valid_items[:count_limit]:
            index = item.get("index")
            domain = item.get("domain") or "unknown"
            title = item.get("source_title") or "无标题"
            content = (item.get("content") or "")[:content_limit]
            cluster_theme = item.get("cluster_theme") or "未分类"
            consensus_level = item.get("consensus_level") or "未评估"
            parts.append(
                f"来源标注：[来源 {index}] {domain} — {title}\n"
                f"聚类主题：{cluster_theme}\n"
                f"共识级别：{consensus_level}\n"
                f"内容：{content}"
            )

        formatted = "\n\n".join(parts)
        if estimate_tokens(formatted) <= settings.TOKEN_BUDGET_SOFT_LIMIT:
            if count_limit < len(valid_items) or content_limit < 1500:
                logger.warning(
                    "Render Evidence 截断: %d→%d 条, content_limit=%d",
                    len(valid_items), count_limit, content_limit,
                )
            return formatted

        if content_limit >= 500:
            content_limit -= 250
            continue

        count_limit -= 1
        content_limit = 1500

    # 兜底保留 1 条最短内容
    item = valid_items[0]
    return (
        f"来源标注：[来源 {item.get('index')}] {item.get('domain') or 'unknown'} — "
        f"{item.get('source_title') or '无标题'}\n"
        f"聚类主题：{item.get('cluster_theme') or '未分类'}\n"
        f"共识级别：{item.get('consensus_level') or '未评估'}\n"
        f"内容：{(item.get('content') or '')[:250]}"
    )


def _summarize_clusters(clusters: list[dict]) -> str:
    """把 clusters 数组概括为单行文本。"""
    if not clusters:
        return "无"
    parts = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        theme = c.get("theme") or "未命名"
        consensus = c.get("consensus_level") or "未知"
        indices = c.get("evidence_indices") or []
        parts.append(f"{theme}（共识度：{consensus}，证据：{len(indices)} 条）")
    return "；".join(parts) if parts else "无"


def _summarize_conflicts(conflicts: list[dict]) -> str:
    """把 conflicts 数组概括为单行文本。"""
    if not conflicts:
        return "无"
    parts = []
    for c in conflicts:
        if not isinstance(c, dict):
            continue
        topic = c.get("topic") or "未命名分歧"
        pos_a = c.get("position_a") or {}
        pos_b = c.get("position_b") or {}
        summary_a = (pos_a.get("summary") or "")[:60]
        summary_b = (pos_b.get("summary") or "")[:60]
        parts.append(f"{topic}（A：{summary_a} / B：{summary_b}）")
    return "；".join(parts) if parts else "无"


def _build_render_prompt(
    topic: str,
    task_type: str,
    language: str,
    template_name: str,
    template_desc: str,
    graph: dict,
    items: list[dict],
) -> list[dict[str, str]]:
    """构建 Render Prompt。"""
    clusters_summary = _summarize_clusters(graph.get("clusters") or [])
    conflicts_summary = _summarize_conflicts(graph.get("conflicts") or [])
    gaps = graph.get("knowledge_gaps") or []
    gaps_text = "；".join(gaps) if gaps else "无"

    evidence_items_formatted = _format_evidence_items(items)

    sections_schema = '''{
  "sections": [
    {
      "heading": "1. 章节标题",
      "content": "Markdown 正文，每个事实性陈述后使用 [来源N] 标注引用，N 为证据详情中的 0-based 编号"
    }
  ]
}'''

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        topic=topic,
        task_type=task_type,
        language=language,
        template=template_name,
        template_sections_description=template_desc,
        item_count=len(items),
        clusters_summary=clusters_summary,
        conflicts_summary=conflicts_summary,
        knowledge_gaps=gaps_text,
        evidence_items_formatted=evidence_items_formatted,
        sections_json_schema=sections_schema,
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请基于上述研究证据图谱撰写报告，输出严格 JSON 格式。"},
    ]


async def _call_llm_render(messages: list[dict[str, str]]) -> tuple[str, LLMResult, int]:
    """调用 LLM 渲染报告，失败/解析异常时重试。

    Returns:
        (raw_text, llm_result, retry_count)
    """
    max_retries = settings.PIPELINE_RENDER_MAX_RETRIES
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = await chat_completion(
                messages,
                model=settings.LLM_MODEL,
                max_tokens=8000,
                temperature=0.5,
                deep_thinking=False,
            )
            # 初步校验：必须能解析出含 sections 的 JSON
            json_text = _extract_json_from_text(result.content)
            data = json.loads(json_text)
            if not isinstance(data, dict):
                raise ValueError("LLM 输出不是 JSON 对象")
            if "sections" not in data:
                raise ValueError("LLM 输出缺少 sections 字段")
            return result.content, result, attempt
        except Exception as e:
            last_error = e
            logger.warning(
                "Render LLM 调用/解析失败（尝试 %d/%d）: %s",
                attempt + 1,
                max_retries + 1,
                e,
            )
            if attempt < max_retries:
                continue
            break

    detail = f"报告渲染失败（重试 {max_retries} 次后仍失败）"
    if last_error:
        detail = f"{detail}: {last_error}"
    raise RenderFailedException(detail=detail)


# 匹配 LLM 可能输出的各种非标准引用变体：
# [来源N] / [来源 N] / [来源N,M] / [来源N，M] / [来源N-M] / [来源 N, M]
_CITATION_NORMALIZE_RE = re.compile(r"\[\s*来源\s*(\d+(?:\s*[,，\-]\s*\d+)*)\s*\]")


def normalize_citation_markup(content: str, valid_count: int | None = None) -> str:
    """将 LLM 输出的非标准引用格式规范化为独立的 `[来源N]`。

    处理场景：
    - `[来源 4]` → `[来源4]`（去除来源与数字间的空格）
    - `[来源4, 5]` / `[来源4,5]` / `[来源4，5]` → `[来源4][来源5]`
    - `[来源4-5]` → `[来源4][来源5]`

    同时做保守的 1-based → 0-based 修正：当 valid_count 已知且
    引用中最大值等于 valid_count（即 evidence 总数）时，认为 LLM
    误用了 1-based 索引，统一减 1。

    Args:
        content: 章节 Markdown 正文。
        valid_count: evidence 条目总数（0-based 最大索引 + 1）。
                     为 None 时跳过 1-based 修正。

    Returns:
        规范化后的正文。
    """

    def _replace(match: re.Match) -> str:
        raw = match.group(1)
        parts = re.split(r"\s*[,，\-]\s*", raw)
        indices: list[int] = []
        for part in parts:
            try:
                indices.append(int(part))
            except ValueError:
                continue
        if not indices:
            return match.group(0)

        # 保守 1-based 检测：最大值恰好等于 evidence 总数时，认为 LLM 从 1 开始计数
        if valid_count is not None and valid_count > 0:
            max_idx = max(indices)
            if max_idx == valid_count and all(i >= 1 for i in indices):
                indices = [i - 1 for i in indices]

        return "".join(f"[来源{i}]" for i in indices)

    return _CITATION_NORMALIZE_RE.sub(_replace, content)


_CITATION_RE = re.compile(r"\[来源\s*(\d+)\]")


def _extract_citations(
    content: str,
    index_to_item: dict[int, dict],
) -> tuple[list[dict], bool]:
    """从正文提取 [来源N] 引用。

    Returns:
        (sources, has_invalid_citation)
    """
    matches = _CITATION_RE.findall(content)
    indices: list[int] = []
    has_invalid = False

    for m in matches:
        try:
            idx = int(m)
        except ValueError:
            has_invalid = True
            continue
        if idx in index_to_item:
            indices.append(idx)
        else:
            has_invalid = True

    unique_sorted = sorted(set(indices))
    sources = [
        {"id": index_to_item[idx]["source_id"], "evidence_index": idx}
        for idx in unique_sorted
    ]
    return sources, has_invalid


def _parse_render_output(
    raw_text: str,
    index_to_item: dict[int, dict],
) -> tuple[list[RenderSection], bool]:
    """解析 LLM 输出为 RenderSection 列表。"""
    json_text = _extract_json_from_text(raw_text)
    data = json.loads(json_text)

    if not isinstance(data, dict):
        raise ValueError("LLM 输出不是 JSON 对象")

    sections_raw = data.get("sections")
    if not isinstance(sections_raw, list):
        raise ValueError("缺少 sections 数组")

    valid_count = len(index_to_item)
    sections: list[RenderSection] = []
    citation_issues = False

    for i, s in enumerate(sections_raw):
        if not isinstance(s, dict):
            raise ValueError(f"sections[{i}] 不是对象")

        heading = str(s.get("heading", "")).strip()
        content = str(s.get("content", "")).strip()
        if not heading:
            raise ValueError(f"sections[{i}].heading 为空")
        if not content:
            raise ValueError(f"sections[{i}].content 为空")

        # 规范化 LLM 可能输出的非标准引用格式
        content = normalize_citation_markup(content, valid_count)

        sources, has_invalid = _extract_citations(content, index_to_item)
        if has_invalid:
            citation_issues = True
        if not sources:
            citation_issues = True

        sections.append(RenderSection(heading=heading, content=content, sources=sources))

    return sections, citation_issues


async def _persist_sections(
    session: AsyncSession,
    task_id: str,
    sections: list[RenderSection],
    index_to_evidence_id: dict[int, int],
) -> list[ReportSection]:
    """写入 report_sections 并建立 section_evidence 关联。"""
    report_sections: list[ReportSection] = []
    for i, section in enumerate(sections):
        rs = ReportSection(
            task_id=task_id,
            heading=section.heading,
            content=section.content,
            sort_order=i,
        )
        session.add(rs)
        report_sections.append(rs)

    await session.flush()

    for rs, section in zip(report_sections, sections):
        for src in section.sources:
            evidence_id = index_to_evidence_id.get(src["evidence_index"])
            if evidence_id is None:
                continue
            se = SectionEvidence(section_id=rs.id, evidence_id=evidence_id)
            session.add(se)

    await session.flush()
    return report_sections


async def _update_evidence_used_in_sections(
    session: AsyncSession,
    task_id: str,
    sections: list[RenderSection],
    index_to_evidence_id: dict[int, int],
) -> None:
    """更新 evidence_items.used_in_sections JSON。"""
    usage: dict[int, list[str]] = {}
    for i, section in enumerate(sections):
        section_label = str(i + 1)
        for src in section.sources:
            evidence_id = index_to_evidence_id.get(src["evidence_index"])
            if evidence_id is None:
                continue
            usage.setdefault(evidence_id, []).append(section_label)

    if not usage:
        return

    evidence_ids = list(usage.keys())
    stmt = (
        select(EvidenceItem)
        .where(
            EvidenceItem.id.in_(evidence_ids),
            EvidenceItem.task_id == task_id,
        )
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    for item in items:
        existing = item.used_in_sections or []
        if not isinstance(existing, list):
            existing = []
        merged = set(existing) | set(usage.get(item.id, []))
        item.used_in_sections = sorted(
            merged,
            key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0,
        )


# ── 上游数据读取 ──────────────────────────────────────────────


async def _load_evidence_graph(
    session: AsyncSession,
    task: ResearchTask,
) -> dict:
    """读取最新 completed Evidence Graph Step 的 output["graph"]。"""
    stmt = (
        select(ResearchStep)
        .where(
            ResearchStep.task_id == task.id,
            ResearchStep.step_type == "evidence_graph",
            ResearchStep.status == "completed",
        )
        .order_by(ResearchStep.completed_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    step: ResearchStep | None = result.scalar_one_or_none()

    if step is None or step.output is None:
        raise RenderFailedException(detail="缺少已完成的 Evidence Graph Step")

    if not isinstance(step.output, dict):
        raise RenderFailedException(detail="Evidence Graph Step output 格式异常，应为 JSON 对象")

    graph = step.output.get("graph")
    if not isinstance(graph, dict):
        raise RenderFailedException(detail="Evidence Graph Step output 缺少 graph 字段")

    return graph


# ── 主入口 ────────────────────────────────────────────────────


async def run_render(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse: SSEBridge,
) -> dict:
    """执行 Report Render 阶段。

    1. 读取 Evidence Graph
    2. 选择模板并构建 Prompt
    3. 调用 LLM（含重试）
    4. 解析 Section 与引用
    5. 持久化 report_sections / section_evidence
    6. 更新 evidence_items.used_in_sections
    7. 发布 SSE 事件
    8. 返回 output dict（含渲染指标）
    """
    task_id = str(task.id)
    step_id = str(step.id)

    requirements = task.requirements or {}
    task_type = requirements.get("task_type", "explainer")
    language = requirements.get("language", "zh")

    logger.info("Report Render 开始: task_id=%s, task_type=%s", task_id, task_type)

    # 1. 读取 Evidence Graph
    graph = await _load_evidence_graph(session, task)
    items = graph.get("items") or []
    if not items:
        raise RenderFailedException(detail="Evidence Graph 为空，无法渲染报告")

    index_to_item: dict[int, dict] = {}
    index_to_evidence_id: dict[int, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if idx is None:
            continue
        index_to_item[idx] = item
        evidence_item_id = item.get("evidence_item_id")
        if evidence_item_id is not None:
            index_to_evidence_id[idx] = evidence_item_id

    if not index_to_item:
        raise RenderFailedException(detail="Evidence Graph items 缺少有效 index")

    # 2. 选择模板并构建 Prompt
    template_name, template_desc = _select_template(task_type)
    messages = _build_render_prompt(
        topic=task.topic,
        task_type=task_type,
        language=language,
        template_name=template_name,
        template_desc=template_desc,
        graph=graph,
        items=items,
    )

    # 3. 发布初始进度
    expected_sections = {
        "comparison": 5,
        "explainer": 4,
        "analysis": 5,
    }.get(task_type, 4)
    await sse.publish(EVENT_STEP_PROGRESS, {
        "step_id": step_id,
        "phase": "rendering",
        "label": f"正在渲染报告（预计 {expected_sections} 个章节）...",
        "sections_completed": 0,
        "total_sections": expected_sections,
    })

    # 4. 调用 LLM（含重试）
    raw_text, llm_result, retry_count = await _call_llm_render(messages)

    # 5. 解析 Section 与引用
    sections, citation_issues = _parse_render_output(raw_text, index_to_item)

    # 6. 持久化
    await _persist_sections(session, task_id, sections, index_to_evidence_id)
    await _update_evidence_used_in_sections(session, task_id, sections, index_to_evidence_id)

    # 7. 计算耗时
    duration_ms = 0
    if step.started_at:
        delta = datetime.now(timezone.utc) - step.started_at
        duration_ms = int(delta.total_seconds() * 1000)

    # 8. 发布进度与完成事件
    citations_count = sum(len(s.sources) for s in sections)
    await sse.publish(EVENT_STEP_PROGRESS, {
        "step_id": step_id,
        "phase": "rendering",
        "label": f"报告渲染完成：{len(sections)} 个章节，{citations_count} 处引用",
        "sections_completed": len(sections),
        "total_sections": len(sections),
    })
    await sse.publish(EVENT_STEP_COMPLETED, {
        "step_id": step_id,
        "sections_count": len(sections),
        "citations_count": citations_count,
    })

    output = {
        "sections_count": len(sections),
        "citations_count": citations_count,
        "template": template_name,
        "model": settings.LLM_MODEL,
        "retry_count": retry_count,
        "prompt_tokens": llm_result.prompt_tokens,
        "completion_tokens": llm_result.completion_tokens,
        "duration_ms": duration_ms,
        "citation_issues": citation_issues,
    }

    logger.info(
        "Report Render 完成: task_id=%s, sections=%d, citations=%d, retry=%d, issues=%s",
        task_id,
        len(sections),
        citations_count,
        retry_count,
        citation_issues,
    )

    return output
