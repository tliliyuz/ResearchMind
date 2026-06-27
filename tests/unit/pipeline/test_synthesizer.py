"""Synthesis 阶段单元测试 —— 跨源综合、LLM 重试、输出校验。"""
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.exceptions import SynthesisFailedException
from app.core.llm import LLMResult
from app.models.evidence_item import EvidenceItem
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.user import User
from app.pipeline.sse_bridge import EVENT_STEP_COMPLETED, EVENT_STEP_PROGRESS
from app.pipeline.synthesizer import run_synthesis


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _make_llm_result(notes: dict) -> LLMResult:
    """构造 Synthesis LLM 返回结果。"""
    return LLMResult(
        content=json.dumps(notes, ensure_ascii=False),
        reasoning_content="",
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
    )


_UNSET = object()


def _valid_notes(conflicts: Any = _UNSET, supporting_indices: list[int] | None = None) -> dict:
    """生成有效 SynthesisNotes JSON。

    conflicts=_UNSET 时使用默认的一个冲突；
    conflicts=None 时输出 null（用于测试 null → 空数组）。
    """
    if conflicts is _UNSET:
        conflicts = [
            {
                "topic": "标准化时间表分歧",
                "position_a": {"summary": "NIST 2024 年发布最终标准", "evidence_indices": [0]},
                "position_b": {"summary": "业界认为需更长时间验证", "evidence_indices": [1]},
            }
        ]

    return {
        "clusters": [
            {
                "theme": "量子计算威胁",
                "summary": "量子计算对 RSA 和 ECC 构成实际威胁。",
                "consensus_level": "strong",
                "supporting_evidence_indices": supporting_indices or [0, 1],
                "conflicting_evidence_indices": [],
            }
        ],
        "conflicts": conflicts,
        "knowledge_gaps": ["量子计算机实际错误率数据"],
        "overall_assessment": "证据质量较高，但缺少具体量化数据。",
    }


async def _seed_synthesis_task(
    db_session,
    task_type: str = "analysis",
    max_sources: int = 10,
    evidence_count: int = 3,
    evidence_contents: list[str] | None = None,
    relevance_scores: list[float] | None = None,
    task_suffix: str = "001",
) -> tuple[ResearchTask, ResearchStep]:
    """在测试数据库中预置一个可进入 Synthesis 的任务。

    Returns:
        (task, synthesis_step)
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
        id=f"task-synthesis-{task_suffix}",
        user_id=1,
        topic="量子计算对密码学的影响",
        requirements={
            "task_type": task_type,
            "depth": "quick",
            "max_sources": max_sources,
            "language": "zh",
        },
        status="running",
        total_steps=3,
        completed_steps=2,
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
            "sub_questions": ["量子计算威胁", "PQC 标准化进展"],
            "rationale": "两维度拆解",
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
        status="completed",
        label="Rerank",
        output={"evidence_count": evidence_count},
        started_at=datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
        duration_ms=1000,
    )
    db_session.add(rerank_step)

    contents = evidence_contents or [
        "量子计算对 RSA 算法构成严重威胁，Shor 算法可多项式时间分解大整数。",
        "NIST 正在推进后量子密码标准化，预计 2024 年发布最终标准。",
        "中国在量子安全通信领域投入大量资源，已建设量子通信骨干网。",
    ]
    scores = relevance_scores or [0.95, 0.85, 0.75]

    for i in range(evidence_count):
        source = ResearchSource(
            task_id=task.id,
            url=f"https://example.com/source-{i}",
            title=f"来源 {i}",
            domain="example.com",
            content=contents[i] if i < len(contents) else f"内容 {i}",
            fetch_status="success",
            fetched_at=datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
        )
        db_session.add(source)
        await db_session.flush()

        ev = EvidenceItem(
            task_id=task.id,
            source_id=source.id,
            step_id=rerank_step.id,
            content=contents[i] if i < len(contents) else f"内容 {i}",
            relevance_score=scores[i] if i < len(scores) else 0.5,
        )
        db_session.add(ev)

    synthesis_step = ResearchStep(
        id=f"step-synthesis-{task_suffix}",
        task_id=task.id,
        step_type="synthesis",
        status="running",
        label="Synthesis",
        started_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
    )
    db_session.add(synthesis_step)

    await db_session.flush()
    return task, synthesis_step


# ═══════════════════════════════════════════════════════════════
# 成功路径
# ═══════════════════════════════════════════════════════════════


class TestSynthesisSuccess:
    """Synthesis 正常流程。"""

    @pytest.mark.asyncio
    async def test_正常综合产出完整output并发送SSE(self, db_session):
        """正常综合产出 clusters/conflicts/gaps/overall_assessment，output 完整。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=2)
        sse = MagicMock()
        notes = _valid_notes()

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(notes)
            output = await run_synthesis(task, synthesis_step, db_session, sse)

        assert output["clusters_count"] == 1
        assert output["conflicts_count"] == 1
        assert output["gaps_count"] == 1
        assert output["clusters"][0]["theme"] == "量子计算威胁"
        assert output["overall_assessment"] == "证据质量较高，但缺少具体量化数据。"
        assert output["model"] == "deepseek-v4-pro"
        assert output["retry_count"] == 0
        assert output["prompt_tokens"] == 1000
        assert output["completion_tokens"] == 500
        assert output["evidence_count"] == 2

        progress_calls = [c for c in sse.publish.call_args_list if c.args[0] == EVENT_STEP_PROGRESS]
        completed_calls = [c for c in sse.publish.call_args_list if c.args[0] == EVENT_STEP_COMPLETED]
        assert len(progress_calls) == 2
        assert "跨源综合" in progress_calls[0].args[1]["label"]
        assert progress_calls[1].args[1]["clusters_count"] == 1
        assert "观点聚类" in progress_calls[1].args[1]["label"]
        assert len(completed_calls) == 1
        assert completed_calls[0].args[1]["clusters_count"] == 1

    @pytest.mark.asyncio
    async def test_Evidence按relevance_score降序并截断1500字符(self, db_session):
        """Evidence 按 relevance_score 降序，单条内容截断至 1500 字符，0-based 索引。"""
        long_content = "A" * 2000
        task, synthesis_step = await _seed_synthesis_task(
            db_session,
            evidence_count=3,
            evidence_contents=[
                long_content,
                "第二条证据。",
                "第三条证据。",
            ],
            relevance_scores=[0.9, 0.95, 0.8],
        )
        sse = MagicMock()
        captured_messages = []

        async def _capture_and_return(*args, **kwargs):
            captured_messages.append(kwargs.get("messages"))
            return _make_llm_result(_valid_notes(supporting_indices=[0, 1, 2]))

        with patch("app.pipeline.synthesizer.chat_completion", new=_capture_and_return):
            await run_synthesis(task, synthesis_step, db_session, sse)

        system_content = captured_messages[0][0]["content"]
        # 0.95 应排在 [来源 0]，0.9 排在 [来源 1]，0.8 排在 [来源 2]
        assert system_content.index("[来源 0]") < system_content.index("[来源 1]")
        assert system_content.index("[来源 1]") < system_content.index("[来源 2]")
        assert "A" * 1500 in system_content
        assert "A" * 1501 not in system_content

    @pytest.mark.asyncio
    async def test_max_sources截断Evidence数量(self, db_session):
        """max_sources=3 截断 5 条 evidence → prompt 中仅 3 块。"""
        task, synthesis_step = await _seed_synthesis_task(
            db_session,
            max_sources=3,
            evidence_count=5,
            evidence_contents=[f"证据 {i}" for i in range(5)],
            relevance_scores=[0.9 - i * 0.05 for i in range(5)],
        )
        sse = MagicMock()
        captured_messages = []

        async def _capture_and_return(*args, **kwargs):
            captured_messages.append(kwargs.get("messages"))
            return _make_llm_result(_valid_notes(supporting_indices=[0, 1, 2]))

        with patch("app.pipeline.synthesizer.chat_completion", new=_capture_and_return):
            output = await run_synthesis(task, synthesis_step, db_session, sse)

        system_content = captured_messages[0][0]["content"]
        # 只有 [来源 0/1/2]
        assert "[来源 0]" in system_content
        assert "[来源 1]" in system_content
        assert "[来源 2]" in system_content
        assert "[来源 3]" not in system_content
        assert "[来源 4]" not in system_content
        assert output["evidence_count"] == 3

    @pytest.mark.asyncio
    async def test_三种task_type均出现在Prompt(self, db_session):
        """comparison / explainer / analysis 三种 task_type 均出现在 system prompt。"""
        captured_messages = []

        async def _capture_and_return(*args, **kwargs):
            captured_messages.append(kwargs.get("messages"))
            return _make_llm_result(_valid_notes())

        for idx, task_type in enumerate(("comparison", "explainer", "analysis"), start=1):
            task, synthesis_step = await _seed_synthesis_task(
                db_session,
                task_type=task_type,
                task_suffix=f"type-{idx:03d}",
            )
            sse = MagicMock()

            with patch("app.pipeline.synthesizer.chat_completion", new=_capture_and_return):
                await run_synthesis(task, synthesis_step, db_session, sse)

            system_content = captured_messages[-1][0]["content"]
            assert f"研究类型：{task_type}" in system_content

    @pytest.mark.asyncio
    async def test_conflicts为null_不阻断且输出空数组(self, db_session):
        """LLM 返回 conflicts: null → 不阻断，输出 conflicts==[]。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=2)
        sse = MagicMock()
        notes = _valid_notes(conflicts=None)

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(notes)
            output = await run_synthesis(task, synthesis_step, db_session, sse)

        assert output["conflicts"] == []
        assert output["conflicts_count"] == 0

        completed_calls = [c for c in sse.publish.call_args_list if c.args[0] == EVENT_STEP_COMPLETED]
        assert len(completed_calls) == 1
        assert completed_calls[0].args[1]["conflicts"] == []

    @pytest.mark.asyncio
    async def test_越界索引被过滤不阻断(self, db_session):
        """supporting_evidence_indices 含越界值 → 过滤后建簇。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=2)
        sse = MagicMock()
        notes = _valid_notes(supporting_indices=[0, 1, 999])

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(notes)
            output = await run_synthesis(task, synthesis_step, db_session, sse)

        assert output["clusters"][0]["supporting_evidence_indices"] == [0, 1]


# ═══════════════════════════════════════════════════════════════
# 失败路径
# ═══════════════════════════════════════════════════════════════


class TestSynthesisFailure:
    """Synthesis 失败策略。"""

    @pytest.mark.asyncio
    async def test_无效JSON重试后成功_retry_count为1_call_count为2(self, db_session):
        """第一次返回无效 JSON，第二次成功 → retry_count=1，call_count=2。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=2)
        sse = MagicMock()

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            mock_llm.side_effect = [
                LLMResult(content="不是 JSON", reasoning_content="", prompt_tokens=100, completion_tokens=50, total_tokens=150),
                _make_llm_result(_valid_notes()),
            ]
            output = await run_synthesis(task, synthesis_step, db_session, sse)

        assert mock_llm.call_count == 2
        assert output["retry_count"] == 1
        assert output["clusters_count"] == 1

    @pytest.mark.asyncio
    async def test_无效JSON重试耗尽_抛出E3104_call_count为3(self, db_session):
        """LLM 持续返回无效 JSON，3 次重试耗尽 → E3104。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=2)
        sse = MagicMock()

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            mock_llm.return_value = LLMResult(
                content="不是 JSON",
                reasoning_content="",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            )

            with pytest.raises(SynthesisFailedException) as exc_info:
                await run_synthesis(task, synthesis_step, db_session, sse)

        assert exc_info.value.error_code == "E3104"
        assert mock_llm.call_count == 3

    @pytest.mark.asyncio
    async def test_LLM异常重试耗尽_抛出E3104_call_count为3(self, db_session):
        """LLM 持续异常，3 次重试耗尽 → E3104。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=2)
        sse = MagicMock()

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM 服务不可用")

            with pytest.raises(SynthesisFailedException) as exc_info:
                await run_synthesis(task, synthesis_step, db_session, sse)

        assert exc_info.value.error_code == "E3104"
        assert mock_llm.call_count == 3

    @pytest.mark.asyncio
    async def test_空evidence_抛出E3104_不调用LLM(self, db_session):
        """没有 EvidenceItem → E3104，chat_completion 未被调用。"""
        task, synthesis_step = await _seed_synthesis_task(db_session, evidence_count=0)
        sse = MagicMock()

        with patch("app.pipeline.synthesizer.chat_completion") as mock_llm:
            with pytest.raises(SynthesisFailedException) as exc_info:
                await run_synthesis(task, synthesis_step, db_session, sse)

        assert exc_info.value.error_code == "E3104"
        assert "没有可供综合" in str(exc_info.value.detail)
        assert mock_llm.call_count == 0
