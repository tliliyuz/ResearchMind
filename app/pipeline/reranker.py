"""Rerank 阶段 —— 证据粗筛 + 精排。

对齐 RESEARCH_PIPELINE.md §5：
- Stage 1：BM25 粗筛（jieba 分词 + BM25Okapi，每文档 top-3 segments，最多 45 候选）
- Stage 2：LLM 精排（DeepSeek API，四维评分 0-10，task_type 加权维度）
- 输出 Evidence[] 写入 evidence_items 表

输入来源：
- FetchedDoc[]：从 research_sources 表读取 fetch_status='success' 的行
- SubQuestion[]：从 task 的 planning step output 读取
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import RerankFailedException
from app.core.llm import LLMResult, chat_completion
from app.models.evidence_item import EvidenceItem
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.bm25 import bm25_rerank, segment_document
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_PROGRESS,
    EVENT_TASK_WARNING,
)

logger = logging.getLogger(__name__)

# ── task_type 加权维度（对齐 RESEARCH_PIPELINE.md §5.4）────────

_TASK_TYPE_DIMENSIONS: dict[str, tuple[str, str]] = {
    "comparison": (
        "属性对齐度",
        "内容是否包含可对比的维度信息。偏爱「A 的延迟是 Xms，B 的延迟是 Yms」这类可对齐的事实。",
    ),
    "explainer": (
        "观点新颖度",
        "内容是否提供独特观点而非重复已有信息。偏爱小众但信息密度高的源。",
    ),
    "analysis": (
        "因果关联度",
        "内容是否包含因果推理或影响分析。偏爱含「导致」「因此」「影响」等因果链的内容。",
    ),
}

# ── System Prompt 模板（对齐 RESEARCH_PIPELINE.md §5.4）────────

_SYSTEM_PROMPT_TEMPLATE = """你是一个研究证据评审专家。你需要对以下内容片段进行相关性评分。

研究主题：{topic}
研究类型：{task_type}
子问题：
{sub_questions}

评分标准（0-10）：
- 相关性：内容是否直接回答子问题（权重 40%）
- 信息量：内容是否包含具体数据、事实、观点（权重 30%）
- 权威性：来源是否可靠（.gov/.edu 加分，个人博客减分）（权重 15%）
- {dimension_name}（权重 15%）
  {dimension_desc}

逐条评分，输出严格 JSON 格式：
{{
  "ratings": [
    {{"segment_index": 0, "score": 8.5, "rationale": "一句话理由"}},
    ...
  ]
}}

注意：
- 只输出 JSON，不要包含 markdown 代码块
- 每个 segment_index 必须对应输入片段的序号
- score 必须是 0-10 之间的数字，保留一位小数"""

# ── 数据类型 ──────────────────────────────────────────────────


@dataclass
class FetchedDoc:
    """Fetch 阶段产出的单篇文档（内存结构）。"""
    source_id: int
    url: str
    title: str
    domain: str
    content: str


@dataclass
class Candidate:
    """BM25 粗筛后的候选片段。"""
    source_id: int
    url: str
    title: str
    domain: str
    content: str
    sub_question_index: int
    bm25_score: float


@dataclass
class Evidence:
    """LLM 精排后的证据条目。"""
    source_id: int
    url: str
    title: str
    domain: str
    content: str
    relevance_score: float  # 0-1，由 LLM 0-10 分归一化
    bm25_score: float
    sub_question_index: int
    word_count: int
    rationale: str


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


def _parse_llm_ratings(raw_text: str, expected_count: int) -> list[dict]:
    """解析 LLM 返回的 ratings JSON。

    Raises:
        ValueError: JSON 无效或 ratings 数量不匹配
    """
    json_text = _extract_json_from_text(raw_text)
    data = json.loads(json_text)

    if not isinstance(data, dict):
        raise ValueError("LLM 输出不是 JSON 对象")

    ratings = data.get("ratings")
    if not isinstance(ratings, list):
        raise ValueError("缺少 ratings 数组")

    if len(ratings) != expected_count:
        raise ValueError(f"ratings 数量 {len(ratings)} != 期望 {expected_count}")

    parsed: list[dict] = []
    for i, r in enumerate(ratings):
        if not isinstance(r, dict):
            raise ValueError(f"ratings[{i}] 不是对象")

        segment_index = r.get("segment_index")
        if not isinstance(segment_index, int) or segment_index != i:
            raise ValueError(f"ratings[{i}] segment_index 不匹配")

        score = r.get("score")
        if not isinstance(score, (int, float)):
            raise ValueError(f"ratings[{i}] score 不是数字")
        if score < 0 or score > 10:
            raise ValueError(f"ratings[{i}] score {score} 不在 0-10 范围")

        rationale = r.get("rationale", "")
        if not isinstance(rationale, str):
            rationale = str(rationale)

        parsed.append({
            "segment_index": segment_index,
            "score": float(score),
            "rationale": rationale,
        })

    return parsed


# ── 上游数据读取 ──────────────────────────────────────────────


async def _load_fetched_docs(
    session: AsyncSession,
    task: ResearchTask,
) -> list[FetchedDoc]:
    """从 research_sources 读取成功抓取的文档。"""
    stmt = (
        select(ResearchSource)
        .where(
            ResearchSource.task_id == task.id,
            ResearchSource.fetch_status == "success",
            ResearchSource.content.is_not(None),
        )
        .order_by(ResearchSource.id)
    )
    result = await session.execute(stmt)
    sources: list[ResearchSource] = list(result.scalars().all())

    docs: list[FetchedDoc] = []
    for source in sources:
        if not source.content or not source.content.strip():
            continue
        docs.append(FetchedDoc(
            source_id=source.id,
            url=source.url,
            title=source.title or "",
            domain=source.domain or "",
            content=source.content,
        ))

    return docs


async def _load_sub_questions(
    session: AsyncSession,
    task: ResearchTask,
) -> list[str]:
    """读取 Planning 阶段产出的 sub_questions。

    直接查询 research_steps 中 step_type='planning' 且已完成的那一步，
    避免依赖 step parent_chain 的隐式耦合。
    """
    stmt = (
        select(ResearchStep)
        .where(
            ResearchStep.task_id == task.id,
            ResearchStep.step_type == "planning",
            ResearchStep.status == "completed",
        )
        .order_by(ResearchStep.completed_at)
    )
    result = await session.execute(stmt)
    planning_step: ResearchStep | None = result.scalar_one_or_none()

    if planning_step and planning_step.output and isinstance(planning_step.output, dict):
        sqs = planning_step.output.get("sub_questions", [])
        if isinstance(sqs, list):
            return [str(sq) for sq in sqs if sq]

    return []


# ── BM25 粗筛 ─────────────────────────────────────────────────


def _bm25_stage(
    docs: list[FetchedDoc],
    sub_questions: list[str],
    max_candidates: int = 45,
    top_k_per_doc: int = 3,
    max_segment_chars: int = 2000,
) -> list[Candidate]:
    """BM25 粗筛。

    1. 每篇文档分段
    2. 对每个 sub_question 计算 BM25，取每文档最高分的 segment
    3. 每文档最多保留 top_k_per_doc 个不同 segment
    4. 候选总数不超过 max_candidates
    """
    if not docs or not sub_questions:
        return []

    # 文档 ID → (segment_index, segment_text) 列表
    doc_segments: dict[int, list[tuple[int, str]]] = {}
    doc_by_id: dict[int, FetchedDoc] = {}

    for doc in docs:
        segments = segment_document(doc.content, max_segment_chars)
        doc_by_id[doc.source_id] = doc
        doc_segments[doc.source_id] = list(enumerate(segments))

    candidates: list[Candidate] = []

    for doc in docs:
        segments = [seg for _, seg in doc_segments[doc.source_id]]
        if not segments:
            continue

        # 收集该文档在所有 sub_question 下的最佳 segment
        # key: segment_index, value: 该 segment 在所有 sub_question 中的最高 bm25 分数
        segment_best_score: dict[int, float] = {}
        segment_best_sq: dict[int, int] = {}

        for sq_index, sq in enumerate(sub_questions, start=1):
            top_results = bm25_rerank(segments, sq, top_k=len(segments))
            for seg_idx, score in top_results:
                if seg_idx not in segment_best_score or score > segment_best_score[seg_idx]:
                    segment_best_score[seg_idx] = score
                    segment_best_sq[seg_idx] = sq_index

        # 每文档取 top_k_per_doc 个 segment
        sorted_segments = sorted(
            segment_best_score.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k_per_doc]

        for seg_idx, score in sorted_segments:
            content = segments[seg_idx]
            candidates.append(Candidate(
                source_id=doc.source_id,
                url=doc.url,
                title=doc.title,
                domain=doc.domain,
                content=content,
                sub_question_index=segment_best_sq.get(seg_idx, 0),
                bm25_score=score,
            ))

        if len(candidates) >= max_candidates:
            break

    return candidates[:max_candidates]


# ── LLM 精排 ──────────────────────────────────────────────────


def _build_rerank_prompt(
    topic: str,
    task_type: str,
    sub_questions: list[str],
    candidates: list[Candidate],
) -> tuple[list[dict[str, str]], str]:
    """构建 Rerank Prompt。

    Returns:
        (messages, candidates_text) 用于测试校验
    """
    dimension_name, dimension_desc = _TASK_TYPE_DIMENSIONS.get(
        task_type, _TASK_TYPE_DIMENSIONS["explainer"]
    )

    sub_questions_text = "\n".join(
        f"{i}. {sq}" for i, sq in enumerate(sub_questions, start=1)
    )

    candidates_text = "\n\n".join(
        f"[片段 {i}]\n来源：{c.title or c.domain or c.url}\n{c.content[:1500]}"
        for i, c in enumerate(candidates, start=0)
    )

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        topic=topic,
        task_type=task_type,
        sub_questions=sub_questions_text,
        dimension_name=dimension_name,
        dimension_desc=dimension_desc,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"待评分片段：\n\n{candidates_text}"},
    ]

    return messages, candidates_text


async def _llm_rerank(
    topic: str,
    task_type: str,
    sub_questions: list[str],
    candidates: list[Candidate],
) -> tuple[list[Evidence], int, int, int]:
    """LLM 精排。

    Returns:
        (evidence_list, prompt_tokens, completion_tokens, retry_count)

    Raises:
        RerankFailedException: 重试耗尽或输出无效
    """
    messages, _ = _build_rerank_prompt(topic, task_type, sub_questions, candidates)
    expected_count = len(candidates)

    total_prompt_tokens = 0
    total_completion_tokens = 0
    last_error: Exception | None = None

    for attempt in range(1, settings.PIPELINE_RERANK_MAX_RETRIES + 1):
        try:
            result: LLMResult = await chat_completion(
                messages=messages,
                model=settings.LLM_FLASH_MODEL,
                deep_thinking=False,
                temperature=0.3,
                max_tokens=4000,
            )

            total_prompt_tokens += result.prompt_tokens
            total_completion_tokens += result.completion_tokens

            ratings = _parse_llm_ratings(result.content, expected_count)

            evidence_list: list[Evidence] = []
            for i, rating in enumerate(ratings):
                candidate = candidates[i]
                evidence_list.append(Evidence(
                    source_id=candidate.source_id,
                    url=candidate.url,
                    title=candidate.title,
                    domain=candidate.domain,
                    content=candidate.content,
                    relevance_score=round(rating["score"] / 10.0, 3),
                    bm25_score=candidate.bm25_score,
                    sub_question_index=candidate.sub_question_index,
                    word_count=len(candidate.content),
                    rationale=rating["rationale"],
                ))

            # 按 relevance_score 降序
            evidence_list.sort(key=lambda e: e.relevance_score, reverse=True)
            return evidence_list, total_prompt_tokens, total_completion_tokens, attempt - 1

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning("Rerank LLM 输出解析失败 (attempt %d): %s", attempt, e)
            if attempt < settings.PIPELINE_RERANK_MAX_RETRIES:
                # 追加错误反馈，要求重试
                messages.append({"role": "assistant", "content": result.content if 'result' in dir() else ""})
                messages.append({
                    "role": "user",
                    "content": f"输出格式错误：{e}。请重新输出严格 JSON，确保 ratings 数组长度={expected_count}。",
                })
                continue
            break

        except Exception as e:
            # LLM 客户端内部已做 timeout/rate_limit 重试，这里只捕获最终失败
            last_error = e
            logger.warning("Rerank LLM 调用失败 (attempt %d): %s", attempt, e)
            if attempt < settings.PIPELINE_RERANK_MAX_RETRIES:
                continue
            break

    raise RerankFailedException(
        detail=f"LLM Rerank 失败（{settings.PIPELINE_RERANK_MAX_RETRIES} 次重试耗尽）: {last_error}"
    )


# ── Evidence 持久化 ───────────────────────────────────────────


async def _persist_evidence(
    session: AsyncSession,
    task: ResearchTask,
    step: ResearchStep,
    evidence_list: list[Evidence],
) -> None:
    """将 Evidence[] 写入 evidence_items 表（INSERT only，幂等追加）。"""
    for ev in evidence_list:
        item = EvidenceItem(
            task_id=task.id,
            source_id=ev.source_id,
            step_id=step.id,
            content=ev.content,
            relevance_score=ev.relevance_score,
            used_in_sections=None,
        )
        session.add(item)

    await session.flush()


# ── 主入口 ────────────────────────────────────────────────────


async def run_rerank(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge: SSEBridge,
) -> dict:
    """执行 Rerank 阶段。

    1. 读取 FetchedDoc[] + SubQuestion[]
    2. BM25 粗筛 → candidates
    3. LLM 精排 → Evidence[]
    4. 写入 evidence_items
    5. 更新 task.total_evidence
    6. 发射 SSE 事件

    Returns:
        output dict（写入 step.output）
    """
    task_id = str(task.id)
    step_id = str(step.id)

    requirements = task.requirements or {}
    task_type = requirements.get("task_type", "explainer")
    max_sources = int(requirements.get("max_sources", 10))

    logger.info("Rerank 开始: task_id=%s, task_type=%s, max_sources=%d", task_id, task_type, max_sources)

    # 1. 读取上游数据
    fetched_docs = await _load_fetched_docs(session, task)
    sub_questions = await _load_sub_questions(session, task)

    if not fetched_docs:
        raise RerankFailedException(detail="没有成功抓取的文档可供 Rerank")
    if not sub_questions:
        raise RerankFailedException(detail="缺少 Planning 阶段产出的子问题")

    # 2. BM25 粗筛
    candidates = _bm25_stage(
        fetched_docs,
        sub_questions,
        max_candidates=settings.RERANK_CANDIDATE_MAX,
        top_k_per_doc=settings.RERANK_BM25_TOP_K_PER_DOC,
        max_segment_chars=settings.RERANK_BM25_SEGMENT_MAX_CHARS,
    )

    logger.info("Rerank BM25 粗筛完成: task_id=%s, candidates=%d", task_id, len(candidates))

    sse_bridge.publish(EVENT_STEP_PROGRESS, {
        "step_id": step_id,
        "phase": "reranking",
        "candidates_count": len(candidates),
    })

    if not candidates:
        raise RerankFailedException(detail="BM25 粗筛后候选为空")

    # 3. LLM 精排
    evidence_list, prompt_tokens, completion_tokens, retry_count = await _llm_rerank(
        topic=task.topic,
        task_type=task_type,
        sub_questions=sub_questions,
        candidates=candidates,
    )

    # 4. 取 top-K
    top_k = min(max_sources, len(evidence_list))
    selected_evidence = evidence_list[:top_k]

    # 5. 持久化
    await _persist_evidence(session, task, step, selected_evidence)

    # 6. 更新 task 统计
    task.total_evidence = (task.total_evidence or 0) + len(selected_evidence)
    await session.flush()

    # 7. 质量警告（Evidence < 3 不阻断）
    if len(selected_evidence) < 3:
        sse_bridge.publish(EVENT_TASK_WARNING, {
            "step_id": step_id,
            "error_description": f"精排后 Evidence 数量 {len(selected_evidence)} < 3，可能影响后续综合质量",
        })

    # 8. 聚合统计
    avg_score = round(
        sum(e.relevance_score for e in selected_evidence) / len(selected_evidence), 3
    ) if selected_evidence else 0.0

    top_domains: list[str] = []
    seen_domains: set[str] = set()
    for ev in selected_evidence:
        domain = ev.domain or urlparse(ev.url).netloc or "unknown"
        if domain not in seen_domains:
            seen_domains.add(domain)
            top_domains.append(domain)

    logger.info(
        "Rerank 完成: task_id=%s, evidence=%d, avg_score=%.3f, top_domains=%s",
        task_id, len(selected_evidence), avg_score, top_domains,
    )

    sse_bridge.publish(EVENT_STEP_COMPLETED, {
        "step_id": step_id,
        "evidence_count": len(selected_evidence),
        "avg_score": avg_score,
        "top_domains": top_domains,
    })

    output = {
        "evidence_count": len(selected_evidence),
        "bm25_candidates": len(candidates),
        "avg_score": avg_score,
        "top_domains": top_domains,
        "model": settings.LLM_FLASH_MODEL,
        "retry_count": retry_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }

    return output
