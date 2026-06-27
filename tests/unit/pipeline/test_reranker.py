"""Rerank 阶段单元测试 — BM25 粗筛 + LLM 精排 + Evidence 持久化。"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.exceptions import RerankFailedException
from app.core.llm import LLMResult
from app.models.evidence_item import EvidenceItem
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.user import User
from app.pipeline.reranker import run_rerank
from app.pipeline.sse_bridge import EVENT_STEP_PROGRESS, EVENT_STEP_COMPLETED, EVENT_TASK_WARNING


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _make_llm_result(ratings: list[dict]) -> LLMResult:
    """构造 Rerank LLM 返回结果。"""
    return LLMResult(
        content=json.dumps({"ratings": ratings}, ensure_ascii=False),
        reasoning_content="",
        prompt_tokens=500,
        completion_tokens=200,
        total_tokens=700,
    )


def _valid_ratings(count: int, base_score: float = 8.0) -> list[dict]:
    """生成 count 个有效 rating。"""
    return [
        {"segment_index": i, "score": round(base_score - i * 0.5, 1), "rationale": f"理由{i}"}
        for i in range(count)
    ]


async def _seed_rerank_task(
    db_session,
    task_type: str = "analysis",
    max_sources: int = 5,
    sources_data: list[dict] | None = None,
    task_suffix: str = "001",
) -> tuple[ResearchTask, ResearchStep]:
    """在测试数据库中预置一个可进入 Rerank 的任务。

    Returns:
        (task, rerank_step)
    """
    existing = (await db_session.execute(
        select(User).where(User.id == 1)
    )).scalar_one_or_none()
    if existing is None:
        user = User(
            id=1,
            username="testuser",
            password_hash="$2b$12$dummy",
            role="user",
            status="active",
        )
        db_session.add(user)
        await db_session.flush()

    task = ResearchTask(
        id=f"task-rerank-{task_suffix}",
        user_id=1,
        topic="量子计算对密码学的影响",
        requirements={
            "task_type": task_type,
            "depth": "quick",
            "max_sources": max_sources,
            "language": "zh",
        },
        status="running",
        total_steps=2,
        completed_steps=1,
        total_sources=0,
        total_evidence=0,
    )
    db_session.add(task)
    await db_session.flush()

    planning_step = ResearchStep(
        id=f"step-plan-{task_suffix}",
        task_id=task.id,
        step_type="planning",
        status="completed",
        label="Planning",
        output={
            "sub_questions": [
                "量子计算对RSA和ECC加密算法的具体威胁",
                "NIST后量子密码标准化最新进展",
                "中国在量子安全通信领域的政策与布局",
            ],
            "rationale": "三维度拆解",
        },
        started_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        duration_ms=1000,
    )
    db_session.add(planning_step)

    rerank_step = ResearchStep(
        id=f"step-rerank-{task_suffix}",
        task_id=task.id,
        step_type="rerank",
        status="running",
        label="Rerank",
        started_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
    )
    db_session.add(rerank_step)

    default_sources = sources_data or [
        {
            "url": "https://example.com/quantum-threat",
            "title": "量子计算威胁概述",
            "domain": "example.com",
            "content": "量子计算对 RSA 算法构成严重威胁。\n\nShor 算法可以在多项式时间内分解大整数。",
        },
        {
            "url": "https://nist.gov/pqc/faq",
            "title": "NIST PQC FAQ",
            "domain": "nist.gov",
            "content": "NIST 正在标准化后量子密码算法。\n\nCrystals-Kyber 和 Crystals-Dilithium 是候选算法。",
        },
    ]

    for src in default_sources:
        source = ResearchSource(
            task_id=task.id,
            url=src["url"],
            title=src["title"],
            domain=src["domain"],
            content=src["content"],
            fetch_status="success",
            fetched_at=datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
        )
        db_session.add(source)

    await db_session.flush()
    return task, rerank_step


# ═══════════════════════════════════════════════════════════════
# 成功路径
# ═══════════════════════════════════════════════════════════════


class TestRerankSuccess:
    """Rerank 正常流程。"""

    @pytest.mark.asyncio
    async def test_正常Rerank_产生Evidence并持久化(self, db_session):
        """BM25 + LLM 精排后，EvidenceItem 写入 DB，output 字段完整。"""
        task, rerank_step = await _seed_rerank_task(db_session, max_sources=3)
        sse = MagicMock()

        # 2 个 source × 2 paragraphs × top-3 per doc → 最多 4 candidates
        ratings = _valid_ratings(4)

        with patch("app.pipeline.reranker.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(ratings)
            output = await run_rerank(task, rerank_step, db_session, sse)

        # 验证 evidence 已写入
        result = await db_session.execute(
            select(EvidenceItem).where(EvidenceItem.task_id == task.id)
        )
        items = list(result.scalars().all())
        assert len(items) == 3  # max_sources=3

        # 验证 output
        assert output["evidence_count"] == 3
        assert output["bm25_candidates"] == 4
        assert output["avg_score"] == round(
            sum(r["score"] / 10.0 for r in ratings[:3]) / 3, 3
        )
        assert output["prompt_tokens"] == 500
        assert output["completion_tokens"] == 200
        assert output["model"] == "deepseek-v4-flash"
        assert output["retry_count"] == 0
        assert output["top_domains"] == ["example.com", "nist.gov"]

        # 验证 task 统计更新
        assert task.total_evidence == 3

        # 验证 SSE 进度事件携带 label
        progress_calls = [c for c in sse.publish.call_args_list if c.args[0] == EVENT_STEP_PROGRESS]
        completed_calls = [c for c in sse.publish.call_args_list if c.args[0] == EVENT_STEP_COMPLETED]
        assert len(progress_calls) == 2
        assert "BM25 粗筛完成" in progress_calls[0].args[1]["label"]
        assert "LLM 精排" in progress_calls[1].args[1]["label"]
        assert len(completed_calls) == 1

    @pytest.mark.asyncio
    async def test_task_type维度注入Prompt(self, db_session):
        """不同 task_type 的 Rerank Prompt 包含对应维度描述。"""
        captured_messages = []

        async def _capture_and_return(*args, **kwargs):
            captured_messages.append(kwargs.get("messages"))
            # 2 docs × 2 paragraphs = 4 candidates，返回 4 个评分
            ratings = [
                {"segment_index": i, "score": 7.5 - i * 0.5, "rationale": "ok"}
                for i in range(4)
            ]
            return _make_llm_result(ratings)

        for idx, task_type in enumerate(("comparison", "explainer", "analysis"), start=1):
            task, rerank_step = await _seed_rerank_task(
                db_session, task_type=task_type, task_suffix=f"type-{idx:03d}"
            )
            sse = MagicMock()

            with patch("app.pipeline.reranker.chat_completion", new=_capture_and_return):
                await run_rerank(task, rerank_step, db_session, sse)

            system_content = captured_messages[-1][0]["content"]
            dimension_map = {
                "comparison": "属性对齐度",
                "explainer": "观点新颖度",
                "analysis": "因果关联度",
            }
            assert dimension_map[task_type] in system_content

    @pytest.mark.asyncio
    async def test_Evidence数量不足3_仅触发警告不阻断(self, db_session):
        """max_sources=1 导致只选出 1 条 Evidence，应发 warning 但任务继续。"""
        task, rerank_step = await _seed_rerank_task(db_session, max_sources=1)
        sse = MagicMock()

        ratings = _valid_ratings(4)

        with patch("app.pipeline.reranker.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(ratings)
            output = await run_rerank(task, rerank_step, db_session, sse)

        assert output["evidence_count"] == 1
        assert task.total_evidence == 1

        # 验证 warning 事件
        warning_calls = [
            call for call in sse.publish.call_args_list
            if call.args[0] == "task.warning"
        ]
        assert len(warning_calls) == 1
        assert "Evidence 数量" in warning_calls[0].args[1]["error_description"]


# ═══════════════════════════════════════════════════════════════
# 失败路径
# ═══════════════════════════════════════════════════════════════


class TestRerankFailure:
    """Rerank 失败策略。"""

    @pytest.mark.asyncio
    async def test_无成功Fetch文档_抛出E3105(self, db_session):
        """所有 source 抓取失败时，BM25 候选为空 → E3105。"""
        task, rerank_step = await _seed_rerank_task(
            db_session,
            sources_data=[{
                "url": "https://example.com/fail",
                "title": "失败源",
                "domain": "example.com",
                "content": "",
            }],
        )
        # 覆盖 fetch_status 为失败
        source = (await db_session.execute(
            select(ResearchSource).where(ResearchSource.task_id == task.id)
        )).scalar_one()
        source.fetch_status = "timeout"
        source.content = None
        await db_session.flush()

        sse = MagicMock()

        with pytest.raises(RerankFailedException) as exc_info:
            await run_rerank(task, rerank_step, db_session, sse)

        assert exc_info.value.error_code == "E3105"
        assert "没有成功抓取" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_缺少子问题_抛出E3105(self, db_session):
        """Planning 未产出子问题 → Rerank 无法评分。"""
        task, rerank_step = await _seed_rerank_task(db_session)
        # 清空 planning output 中的子问题
        planning_step = (await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.step_type == "planning",
            )
        )).scalar_one()
        planning_step.output = {"sub_questions": []}
        await db_session.flush()

        sse = MagicMock()

        with pytest.raises(RerankFailedException) as exc_info:
            await run_rerank(task, rerank_step, db_session, sse)

        assert exc_info.value.error_code == "E3105"
        assert "子问题" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_LLM返回无效JSON_重试后仍失败_抛出E3105(self, db_session):
        """LLM 返回非 JSON，重试 2 次后仍失败 → E3105。"""
        task, rerank_step = await _seed_rerank_task(db_session)
        sse = MagicMock()

        with patch("app.pipeline.reranker.chat_completion") as mock_llm:
            mock_llm.return_value = LLMResult(
                content="这不是 JSON",
                reasoning_content="",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            )

            with pytest.raises(RerankFailedException) as exc_info:
                await run_rerank(task, rerank_step, db_session, sse)

        assert exc_info.value.error_code == "E3105"
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_LLM重试耗尽_抛出E3105(self, db_session):
        """LLM 持续异常，重试耗尽 → E3105。"""
        task, rerank_step = await _seed_rerank_task(db_session)
        sse = MagicMock()

        with patch("app.pipeline.reranker.chat_completion") as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM 服务不可用")

            with pytest.raises(RerankFailedException) as exc_info:
                await run_rerank(task, rerank_step, db_session, sse)

        assert exc_info.value.error_code == "E3105"
        assert mock_llm.call_count == 2


# ═══════════════════════════════════════════════════════════════
# 评分与排序
# ═══════════════════════════════════════════════════════════════


class TestRerankScoring:
    """LLM 评分归一化与排序。"""

    @pytest.mark.asyncio
    async def test_Evidence按relevance_score降序排列(self, db_session):
        """LLM 给不同 score，最终 Evidence 按 relevance_score 降序。"""
        task, rerank_step = await _seed_rerank_task(db_session, max_sources=10)
        sse = MagicMock()

        ratings = [
            {"segment_index": 0, "score": 5.0, "rationale": "低"},
            {"segment_index": 1, "score": 9.0, "rationale": "高"},
            {"segment_index": 2, "score": 7.0, "rationale": "中"},
            {"segment_index": 3, "score": 8.0, "rationale": "中高"},
        ]

        with patch("app.pipeline.reranker.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(ratings)
            await run_rerank(task, rerank_step, db_session, sse)

        result = await db_session.execute(
            select(EvidenceItem).where(EvidenceItem.task_id == task.id)
        )
        items = list(result.scalars().all())
        scores = [float(item.relevance_score) for item in items]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 0.9

    @pytest.mark.asyncio
    async def test_relevance_score范围0到1(self, db_session):
        """LLM 0-10 分应归一化为 0-1 存入 evidence_items。"""
        task, rerank_step = await _seed_rerank_task(db_session, max_sources=2)
        sse = MagicMock()

        ratings = [
            {"segment_index": 0, "score": 0.0, "rationale": "最低"},
            {"segment_index": 1, "score": 10.0, "rationale": "最高"},
            {"segment_index": 2, "score": 5.0, "rationale": "中"},
            {"segment_index": 3, "score": 3.0, "rationale": "低"},
        ]

        with patch("app.pipeline.reranker.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(ratings)
            await run_rerank(task, rerank_step, db_session, sse)

        result = await db_session.execute(
            select(EvidenceItem).where(EvidenceItem.task_id == task.id)
        )
        items = list(result.scalars().all())
        # 按 score 降序：10.0 → 5.0，取前 2
        assert float(items[0].relevance_score) == 1.0
        assert float(items[1].relevance_score) == 0.5
