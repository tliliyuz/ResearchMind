"""Pipeline 端到端集成测试（全链路） — Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render。

验证：
- 全 7 阶段在 PipelineOrchestrator 调度下串行跑通
- 各阶段数据真实流转（DB 写入/读取）
- SSE 事件序列完整（含 task.created / phase.* / step.* / checkpoint.saved / task.completed）
- Report 正确产出（report_sections + section_evidence + evidence_items.used_in_sections）
"""
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.llm import LLMResult
from app.core.trace_recorder import TraceRecorder
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.section_evidence import SectionEvidence
from app.models.user import User
from app.pipeline.reranker import Evidence
from app.pipeline.sse_bridge import SSEBridge
from app.pipeline.synthesizer import ConflictPosition, SynthesisCluster, SynthesisConflict, SynthesisNotes
from app.services.pipeline_orchestrator import PipelineOrchestrator, build_default_phase_handlers


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _make_llm_result(content: str, prompt_tokens: int = 100, completion_tokens: int = 50) -> LLMResult:
    """构造 LLMResult。"""
    return LLMResult(
        content=content,
        reasoning_content="",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _valid_planning_json() -> str:
    """返回有效的 Planning 输出 JSON（需满足 3-5 个子问题校验）。"""
    return json.dumps({
        "sub_questions": [
            "量子计算对 RSA/ECC 的具体威胁",
            "NIST 后量子密码标准化最新进展",
            "中国在量子安全通信领域的政策与布局",
        ],
        "rationale": "从技术威胁、标准应对、政策布局三维度拆解",
    }, ensure_ascii=False)


async def _seed_task(db_session) -> ResearchTask:
    """在测试数据库中预置一个待执行全链路的任务。

    Returns:
        已 flush 到测试事务的 ResearchTask 实例。
    """
    existing = await db_session.execute(select(User).where(User.id == 1))
    if existing.scalar_one_or_none() is None:
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
        id="task-full-001",
        user_id=1,
        topic="量子计算对网络安全的威胁与应对策略",
        requirements={
            "task_type": "analysis",
            "depth": "quick",
            "max_sources": 5,
            "language": "zh",
        },
        status="pending",
        total_steps=7,
        completed_steps=0,
        total_sources=0,
        total_evidence=0,
    )
    db_session.add(task)
    await db_session.flush()

    planning_step = ResearchStep(
        id="step-plan-full-001",
        task_id=task.id,
        step_type="planning",
        status="pending",
        label="Planning：拆解研究主题",
        parent_step=None,
    )
    db_session.add(planning_step)
    await db_session.flush()

    return task


def _build_tavily_side_effect():
    """构造 Search 阶段 Tavily Mock side_effect。"""
    async def _side_effect(query: str, api_key: str) -> dict:
        # 根据查询内容返回不同 URL，便于后续去重验证
        if "RSA" in query or "ECC" in query:
            prefix = "threat"
        else:
            prefix = "standard"
        return {
            "results": [
                {
                    "url": f"https://example.com/{prefix}-article{i}",
                    "title": f"{prefix.title()} Article {i}",
                    "score": 0.95 - i * 0.05,
                }
                for i in range(1, 3)
            ],
        }
    return _side_effect


def _build_fetch_side_effect():
    """构造 Fetch 阶段 HTTP Mock side_effect。"""
    async def _side_effect(url: str) -> dict:
        return {
            "status": "success",
            "content": f"# {url.split('/')[-1]} 标题\n\n这是关于 {url} 的正文，"
                       f"包含量子计算和网络安全相关信息，用于测试报告生成。",
            "content_length": 180,
        }
    return _side_effect


def _build_rerank_side_effect(db_session, task_id: str):
    """构造 Rerank 阶段 Mock side_effect：基于真实 DB 中的 ResearchSource 生成 Evidence。"""
    async def _side_effect(topic: str, task_type: str, sub_questions: list[str], candidates: list):
        result = await db_session.execute(
            select(ResearchSource).where(
                ResearchSource.task_id == task_id,
                ResearchSource.fetch_status == "success",
            )
        )
        sources = list(result.scalars().all())
        evidence_list = []
        for i, source in enumerate(sources):
            evidence_list.append(Evidence(
                source_id=source.id,
                url=source.url,
                title=source.title or "",
                domain=source.domain or "",
                content=source.content or "",
                relevance_score=round(0.9 - i * 0.05, 3),
                bm25_score=1.0,
                sub_question_index=0,
                word_count=len(source.content or ""),
                rationale="与问题高度相关",
            ))
        evidence_list.sort(key=lambda e: e.relevance_score, reverse=True)
        return evidence_list, 500, 200, 0
    return _side_effect


def _build_synthesis_side_effect():
    """构造 Synthesis 阶段 Mock side_effect。"""
    async def _side_effect(topic: str, task_type: str, evidence_items_formatted: str, evidence_count: int):
        notes = SynthesisNotes(
            clusters=[
                SynthesisCluster(
                    theme="量子计算威胁",
                    summary="量子计算对 RSA 和 ECC 构成实际威胁。",
                    consensus_level="strong",
                    supporting_evidence_indices=[0, 1],
                    conflicting_evidence_indices=[],
                ),
                SynthesisCluster(
                    theme="后量子密码标准化",
                    summary="NIST 正在推进后量子密码标准制定。",
                    consensus_level="moderate",
                    supporting_evidence_indices=[2],
                    conflicting_evidence_indices=[],
                ),
            ],
            conflicts=[
                SynthesisConflict(
                    topic="标准化时间表分歧",
                    position_a=ConflictPosition("NIST 2024 年发布最终标准", [0]),
                    position_b=ConflictPosition("业界认为需更长时间验证", [1]),
                ),
            ],
            knowledge_gaps=["量子计算机实际错误率数据", "大规模商用时间表"],
            overall_assessment="证据质量较高，但缺少具体量化数据。",
        )
        return notes, 1000, 500, 0
    return _side_effect


def _build_render_side_effect():
    """构造 Render 阶段 Mock side_effect：返回包含 [来源N] 引用的报告。"""
    async def _side_effect(messages: list[dict[str, str]]) -> tuple[str, LLMResult, int]:
        raw_text = json.dumps({
            "sections": [
                {
                    "heading": "1. 概述",
                    "content": "量子计算对 RSA 构成威胁[来源0]，NIST 推进后量子密码标准化[来源1]。",
                },
                {
                    "heading": "2. 威胁分析",
                    "content": "Shor 算法可分解大整数[来源0]，威胁现有公钥体系[来源2]。",
                },
                {
                    "heading": "3. 应对策略",
                    "content": "推进后量子密码迁移是当务之急[来源1]，需制定分阶段路线图[来源2]。",
                },
            ],
        }, ensure_ascii=False)
        return raw_text, _make_llm_result(raw_text, prompt_tokens=2000, completion_tokens=1500), 0
    return _side_effect


# ═══════════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════════


class TestPipelineFullFlow:
    """Pipeline 七阶段全链路集成测试。"""

    @pytest.mark.asyncio
    async def test_全链路_Mock_跑通并产出报告(self, db_session):
        """全 7 阶段 Mock 跑通，验证 DB 状态、SSE 事件、Report 产出。"""
        task = await _seed_task(db_session)
        task_id = task.id

        # SSE 记录器：完全替代 publish，避免测试依赖 Redis
        sse_bridge = SSEBridge(task_id)
        published_events: list[tuple[str, dict | None]] = []

        async def _record_event(event_type, data=None):
            published_events.append((event_type, data))

        sse_bridge.publish = AsyncMock(side_effect=_record_event)

        trace = TraceRecorder(task_id=task_id, user_id=1, topic=task.topic)
        handlers = build_default_phase_handlers()

        patches = [
            patch("app.pipeline.planner.chat_completion", return_value=_make_llm_result(_valid_planning_json())),
            patch("app.pipeline.searcher._call_tavily", side_effect=_build_tavily_side_effect()),
            patch("app.pipeline.fetcher._fetch_one_url", side_effect=_build_fetch_side_effect()),
            patch("app.pipeline.reranker._llm_rerank", side_effect=_build_rerank_side_effect(db_session, task_id)),
            patch("app.pipeline.synthesizer._llm_synthesize", side_effect=_build_synthesis_side_effect()),
            patch("app.pipeline.renderer._call_llm_render", side_effect=_build_render_side_effect()),
            patch("app.tasks.lock.acquire_step_lock_async", return_value=True),
            patch("app.tasks.lock.release_step_lock_async", new_callable=AsyncMock),
        ]

        # Orchestrator 内部会调用 commit；在集成测试中重定向为 flush，
        # 既保证单测事务隔离（fixture 最终 rollback），又避免 commit 后 ORM 对象
        # 过期触发异步懒加载问题。
        original_commit = db_session.commit

        async def _commit_to_flush():
            await db_session.flush()

        db_session.commit = _commit_to_flush
        try:
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                orchestrator = PipelineOrchestrator(
                    task=task,
                    session=db_session,
                    sse_bridge=sse_bridge,
                    trace_recorder=trace,
                    phase_handlers=handlers,
                )
                await orchestrator.run()
        finally:
            db_session.commit = original_commit

        # ── Task 最终状态 ──
        assert task.status == "completed"
        assert task.completed_at is not None
        assert task.completed_steps == 7
        assert task.trace is not None

        # ── 7 个 Phase 均已完成 ──
        steps_result = await db_session.execute(
            select(ResearchStep).where(ResearchStep.task_id == task_id)
        )
        steps = list(steps_result.scalars().all())
        # Orchestrator 创建的 phase step label 来自 PHASE_LABELS，子 step label 不同，据此区分。
        phase_labels = {
            "Planning：拆解研究主题",
            "Search：多子问题搜索",
            "Fetch：网页内容抓取",
            "Rerank：来源粗筛精排",
            "Synthesis：跨源综合",
            "来源图谱：结构化认知资产构建",
            "Render：报告渲染",
        }
        phase_status = {s.step_type: s.status for s in steps if s.label in phase_labels}
        expected_phases = [
            "planning", "search", "fetch", "rerank", "synthesis", "evidence_graph", "render",
        ]
        for phase in expected_phases:
            assert phase_status.get(phase) == "completed", f"Phase {phase} 未完成: {phase_status}"

        # ── Search/Fetch 数据链路 ──
        sources_result = await db_session.execute(
            select(ResearchSource).where(ResearchSource.task_id == task_id)
        )
        sources = list(sources_result.scalars().all())
        assert len(sources) == 4
        assert all(s.fetch_status == "success" for s in sources)
        assert all(s.content is not None and len(s.content) > 0 for s in sources)

        # ── Rerank 数据链路 ──
        evidence_result = await db_session.execute(
            select(EvidenceItem).where(EvidenceItem.task_id == task_id)
        )
        evidence_items = list(evidence_result.scalars().all())
        assert len(evidence_items) == 4
        assert all(ev.source_id in {s.id for s in sources} for ev in evidence_items)

        # ── Render 数据链路 ──
        sections_result = await db_session.execute(
            select(ReportSection).where(ReportSection.task_id == task_id).order_by(ReportSection.sort_order)
        )
        report_sections = list(sections_result.scalars().all())
        assert len(report_sections) == 3
        assert report_sections[0].heading == "1. 概述"
        assert report_sections[1].heading == "2. 威胁分析"
        assert report_sections[2].heading == "3. 应对策略"

        # section_evidence 关联写入
        section_ids = [s.id for s in report_sections]
        se_result = await db_session.execute(
            select(SectionEvidence).where(SectionEvidence.section_id.in_(section_ids))
        )
        se_rows = list(se_result.scalars().all())
        assert len(se_rows) > 0
        associated_evidence_ids = {se.evidence_id for se in se_rows}
        assert associated_evidence_ids.issubset({ev.id for ev in evidence_items})

        # evidence_items.used_in_sections 被回填
        used_evidence = [ev for ev in evidence_items if ev.used_in_sections]
        assert len(used_evidence) > 0

        # ── SSE 事件序列 ──
        event_types = [e[0] for e in published_events]
        assert event_types[0] == "task.created"
        assert event_types[-1] == "task.completed"

        # 关键事件类型至少出现一次
        required_events = {
            "task.created", "task.progress", "task.completed",
            "phase.started", "phase.completed",
            "step.started", "step.completed", "checkpoint.saved",
        }
        assert required_events.issubset(set(event_types))

        # 每个 Phase 都发射了 phase.started 和 phase.completed
        for phase in ["planning", "searching", "fetching", "reranking", "synthesizing", "building_evidence_graph", "rendering"]:
            started = [e for e in published_events if e[0] == "phase.started" and e[1].get("phase") == phase]
            completed = [e for e in published_events if e[0] == "phase.completed" and e[1].get("phase") == phase]
            assert len(started) == 1, f"Phase {phase} 缺少 phase.started"
            assert len(completed) == 1, f"Phase {phase} 缺少 phase.completed"

        # checkpoint.saved 数量 = 7
        checkpoint_count = event_types.count("checkpoint.saved")
        assert checkpoint_count == 7

        # task.progress 最终进度 = 1.0
        progress_events = [e for e in published_events if e[0] == "task.progress"]
        final_progress = progress_events[-1][1]
        assert final_progress["completed_steps"] == 7
        assert final_progress["total_steps"] == 7
        assert final_progress["progress"] == 1.0

        # ── Report 内容 ──
        first_section = report_sections[0]
        assert "量子计算对 RSA 构成威胁" in first_section.content
        assert "[来源0]" in first_section.content

