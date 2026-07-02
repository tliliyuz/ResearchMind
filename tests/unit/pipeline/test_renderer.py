"""Report Render 阶段单元测试 —— 报告渲染、引用提取、持久化。"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.config import settings
from app.core.exceptions import RenderFailedException
from app.core.llm import LLMResult
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.section_evidence import SectionEvidence
from app.models.user import User
from app.pipeline.renderer import run_render, normalize_citation_markup
from app.pipeline.sse_bridge import EVENT_STEP_COMPLETED, EVENT_STEP_PROGRESS


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _valid_evidence_graph(
    evidence_items: list[EvidenceItem] | None = None,
    sources: list[ResearchSource] | None = None,
    task_type: str = "analysis",
) -> dict:
    """生成有效 Evidence Graph JSON。"""
    items = []
    if evidence_items:
        source_map = {s.id: s for s in (sources or [])}
        for i, ev in enumerate(evidence_items):
            source = source_map.get(ev.source_id)
            items.append({
                "index": i,
                "evidence_item_id": ev.id,
                "source_id": ev.source_id,
                "source_url": source.url if source else "",
                "source_title": source.title if source else "无标题",
                "domain": source.domain if source else "unknown",
                "content": ev.content or "",
                "relevance_score": float(ev.relevance_score or 0.0),
                "cluster_theme": "测试聚类",
                "consensus_level": "strong",
                "used_in_sections": [],
            })

    graph_sources = []
    seen_source_ids = set()
    for item in items:
        sid = item["source_id"]
        if sid in seen_source_ids:
            continue
        seen_source_ids.add(sid)
        graph_sources.append({
            "id": sid,
            "url": item["source_url"],
            "title": item["source_title"],
            "domain": item["domain"],
            "evidence_count": 1,
        })

    return {
        "task_id": "task-render-001",
        "generated_at": datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc).isoformat(),
        "items": items,
        "clusters": [
            {
                "theme": "测试聚类",
                "summary": "测试聚类摘要",
                "consensus_level": "strong",
                "evidence_indices": list(range(len(items))),
            }
        ],
        "conflicts": [],
        "knowledge_gaps": [],
        "sources": graph_sources,
    }


def _mock_llm_report(sections: list[dict]) -> LLMResult:
    """构造 Render LLM 返回结果。"""
    return LLMResult(
        content=json.dumps({"sections": sections}, ensure_ascii=False),
        reasoning_content="",
        prompt_tokens=2000,
        completion_tokens=1500,
        total_tokens=3500,
    )


def _valid_report_sections() -> list[dict]:
    """生成包含有效引用的报告章节。"""
    return [
        {
            "heading": "1. 概述",
            "content": "量子计算对 RSA 构成威胁[来源0]，NIST 推进 PQC 标准化[来源1]。",
        },
        {
            "heading": "2. 详细分析",
            "content": "Shor 算法可分解大整数[来源0]，中国建设量子通信骨干网[来源2]。",
        },
    ]


async def _seed_render_task(
    db_session,
    task_type: str = "analysis",
    evidence_count: int = 3,
    evidence_contents: list[str] | None = None,
    relevance_scores: list[float] | None = None,
    graph_overrides: dict | None = None,
    task_suffix: str = "001",
) -> tuple[ResearchTask, ResearchStep, list[EvidenceItem]]:
    """在测试数据库中预置一个可进入 Render 的任务。

    Returns:
        (task, render_step, evidence_items)
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
        id=f"task-render-{task_suffix}",
        user_id=1,
        topic="量子计算对密码学的影响",
        requirements={
            "task_type": task_type,
            "depth": "quick",
            "max_sources": 10,
            "language": "zh",
        },
        status="running",
        total_steps=6,
        completed_steps=5,
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
        output={"sub_questions": ["量子计算威胁"]},
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
    evidence_items: list[EvidenceItem] = []
    source_list: list[ResearchSource] = []

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
        source_list.append(source)

        ev = EvidenceItem(
            task_id=task.id,
            source_id=source.id,
            step_id=rerank_step.id,
            content=contents[i] if i < len(contents) else f"内容 {i}",
            relevance_score=scores[i] if i < len(scores) else 0.5,
        )
        db_session.add(ev)
        await db_session.flush()
        evidence_items.append(ev)

    synthesis_step = ResearchStep(
        id=f"step-synthesis-{task_suffix}",
        task_id=task.id,
        step_type="synthesis",
        status="completed",
        label="Synthesis",
        output={"clusters": [], "conflicts": [], "knowledge_gaps": []},
        started_at=datetime(2026, 1, 1, 0, 0, 4, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
        duration_ms=1000,
    )
    db_session.add(synthesis_step)

    graph = _valid_evidence_graph(evidence_items, source_list, task_type)
    if graph_overrides:
        graph.update(graph_overrides)

    evidence_graph_step = ResearchStep(
        id=f"step-eg-{task_suffix}",
        task_id=task.id,
        step_type="evidence_graph",
        status="completed",
        label="Evidence Graph",
        output={"graph": graph, "item_count": len(evidence_items)},
        started_at=datetime(2026, 1, 1, 0, 0, 6, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc),
        duration_ms=1000,
    )
    db_session.add(evidence_graph_step)

    render_step = ResearchStep(
        id=f"step-render-{task_suffix}",
        task_id=task.id,
        step_type="render",
        status="running",
        label="Render",
        started_at=datetime(2026, 1, 1, 0, 0, 8, tzinfo=timezone.utc),
    )
    db_session.add(render_step)

    await db_session.flush()
    return task, render_step, evidence_items


# ═══════════════════════════════════════════════════════════════
# 成功路径
# ═══════════════════════════════════════════════════════════════


class TestRenderSuccess:
    """Render 正常流程。"""

    @pytest.mark.asyncio
    async def test_正常渲染并持久化report_sections_and_section_evidence(self, db_session):
        """正常渲染产出完整 output，持久化 report_sections 与 section_evidence。"""
        task, render_step, evidence_items = await _seed_render_task(db_session, evidence_count=3)
        sse = AsyncMock()
        sections = _valid_report_sections()

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report(sections)
            output = await run_render(task, render_step, db_session, sse)

        assert output["sections_count"] == 2
        assert output["citations_count"] == 4  # 0,1 + 0,2
        assert output["template"] == "analysis_v1"
        assert output["model"] == settings.LLM_MODEL
        assert output["retry_count"] == 0
        assert output["prompt_tokens"] == 2000
        assert output["completion_tokens"] == 1500
        assert output["citation_issues"] is False

        # 验证 report_sections 写入
        stmt = select(ReportSection).where(ReportSection.task_id == task.id).order_by(ReportSection.sort_order)
        result = await db_session.execute(stmt)
        report_sections = list(result.scalars().all())
        assert len(report_sections) == 2
        assert report_sections[0].heading == "1. 概述"
        assert report_sections[1].heading == "2. 详细分析"

        # 验证 section_evidence 关联
        section_ids = [s.id for s in report_sections]
        stmt = select(SectionEvidence).where(SectionEvidence.section_id.in_(section_ids))
        result = await db_session.execute(stmt)
        associations = list(result.scalars().all())
        assert len(associations) == 4

        # 验证 evidence_items.used_in_sections 更新
        for ev in evidence_items:
            await db_session.refresh(ev)
        assert evidence_items[0].used_in_sections == ["1", "2"]
        assert evidence_items[1].used_in_sections == ["1"]
        assert evidence_items[2].used_in_sections == ["2"]

        progress_calls = [c for c in sse.publish.await_args_list if c.args[0] == EVENT_STEP_PROGRESS]
        completed_calls = [c for c in sse.publish.await_args_list if c.args[0] == EVENT_STEP_COMPLETED]
        assert len(progress_calls) == 2
        assert "渲染报告" in progress_calls[0].args[1]["label"]
        assert "报告渲染完成" in progress_calls[1].args[1]["label"]
        assert len(completed_calls) == 1

    @pytest.mark.asyncio
    async def test_三种task_type模板分支(self, db_session):
        """comparison / explainer / analysis 三种 task_type 选择不同模板。"""
        for idx, task_type in enumerate(("comparison", "explainer", "analysis"), start=1):
            task, render_step, _ = await _seed_render_task(
                db_session,
                task_type=task_type,
                task_suffix=f"type-{idx:03d}",
            )
            sse = AsyncMock()
            sections = [{"heading": "1. 测试", "content": "正文[来源0]。"}]

            with patch("app.pipeline.renderer.chat_completion") as mock_llm:
                mock_llm.return_value = _mock_llm_report(sections)
                output = await run_render(task, render_step, db_session, sse)

            assert output["template"] == f"{task_type}_v1"

    @pytest.mark.asyncio
    async def test_引用按evidence_index去重排序(self, db_session):
        """同一章节内重复引用同一来源只保留一个，并按 evidence_index 排序。"""
        task, render_step, evidence_items = await _seed_render_task(db_session, evidence_count=3)
        sse = AsyncMock()
        sections = [
            {
                "heading": "1. 重复引用测试",
                "content": "RSA[来源2]、RSA 再次[来源2]、NIST[来源0]、中国[来源1]。",
            }
        ]

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report(sections)
            output = await run_render(task, render_step, db_session, sse)

        assert output["citations_count"] == 3

        stmt = select(ReportSection).where(ReportSection.task_id == task.id)
        result = await db_session.execute(stmt)
        report_section = result.scalar_one()

        # 验证 section_evidence 数量 = 去重后 3 条
        stmt = select(SectionEvidence).where(SectionEvidence.section_id == report_section.id)
        result = await db_session.execute(stmt)
        associations = list(result.scalars().all())
        assert len(associations) == 3

    @pytest.mark.asyncio
    async def test_无引用章节标记citation_issues(self, db_session):
        """章节正文无 [来源N] 时 sources 为空且 citation_issues=True。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()
        sections = [
            {"heading": "1. 有引用", "content": "正文[来源0]。"},
            {"heading": "2. 无引用", "content": "正文没有引用。"},
        ]

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report(sections)
            output = await run_render(task, render_step, db_session, sse)

        assert output["citation_issues"] is True

        stmt = select(ReportSection).where(ReportSection.task_id == task.id).order_by(ReportSection.sort_order)
        result = await db_session.execute(stmt)
        report_sections = list(result.scalars().all())
        section_ids = [s.id for s in report_sections]
        stmt = select(SectionEvidence).where(SectionEvidence.section_id.in_(section_ids))
        result = await db_session.execute(stmt)
        associations = list(result.scalars().all())
        section_evidence_counts: dict[int, int] = {}
        for se in associations:
            section_evidence_counts[se.section_id] = section_evidence_counts.get(se.section_id, 0) + 1
        assert section_evidence_counts.get(report_sections[0].id, 0) == 1
        assert section_evidence_counts.get(report_sections[1].id, 0) == 0


# ═══════════════════════════════════════════════════════════════
# 失败路径
# ═══════════════════════════════════════════════════════════════


class TestRenderFailure:
    """Render 失败策略。"""

    @pytest.mark.asyncio
    async def test_无效JSON重试后成功_retry_count为1_call_count为2(self, db_session):
        """第一次返回无效 JSON，第二次成功 → retry_count=1，call_count=2。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.side_effect = [
                LLMResult(content="不是 JSON", reasoning_content="", prompt_tokens=100, completion_tokens=50, total_tokens=150),
                _mock_llm_report([{"heading": "1. 测试", "content": "正文[来源0]。"}]),
            ]
            output = await run_render(task, render_step, db_session, sse)

        assert mock_llm.call_count == 2
        assert output["retry_count"] == 1
        assert output["sections_count"] == 1

    @pytest.mark.asyncio
    async def test_无效JSON重试耗尽_抛出E3107_call_count为2(self, db_session):
        """LLM 持续返回无效 JSON，1 次重试耗尽 → E3107。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = LLMResult(
                content="不是 JSON",
                reasoning_content="",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            )

            with pytest.raises(RenderFailedException) as exc_info:
                await run_render(task, render_step, db_session, sse)

        assert exc_info.value.error_code == "E3107"
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_LLM异常重试耗尽_抛出E3107_call_count为2(self, db_session):
        """LLM 持续异常，1 次重试耗尽 → E3107。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM 服务异常")

            with pytest.raises(RenderFailedException) as exc_info:
                await run_render(task, render_step, db_session, sse)

        assert exc_info.value.error_code == "E3107"
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_section数量不足不阻断(self, db_session):
        """LLM 返回 section 数量少于模板预期，不阻断。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()
        sections = [{"heading": "1. 只有一个章节", "content": "正文[来源0]。"}]

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report(sections)
            output = await run_render(task, render_step, db_session, sse)

        assert output["sections_count"] == 1
        assert output["citation_issues"] is False


# ═══════════════════════════════════════════════════════════════
# 一致性
# ═══════════════════════════════════════════════════════════════


class TestRenderConsistency:
    """Render 一致性与边界情况。"""

    @pytest.mark.asyncio
    async def test_引用指向非法index被过滤并标记citation_issues(self, db_session):
        """正文引用越界 index → 过滤掉并标记 citation_issues。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()
        sections = [
            {
                "heading": "1. 越界引用",
                "content": "有效引用[来源0]，无效引用[来源999]。",
            }
        ]

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report(sections)
            output = await run_render(task, render_step, db_session, sse)

        assert output["citation_issues"] is True
        assert output["citations_count"] == 1

        stmt = select(ReportSection).where(ReportSection.task_id == task.id)
        result = await db_session.execute(stmt)
        report_section = result.scalar_one()
        stmt = select(SectionEvidence).where(SectionEvidence.section_id == report_section.id)
        result = await db_session.execute(stmt)
        associations = list(result.scalars().all())
        assert len(associations) == 1

    @pytest.mark.asyncio
    async def test_空EvidenceGraph_抛出E3107(self, db_session):
        """Evidence Graph items 为空 → E3107。"""
        task, render_step, _ = await _seed_render_task(
            db_session,
            evidence_count=1,
            graph_overrides={"items": []},
        )
        sse = AsyncMock()

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report([{"heading": "1. 测试", "content": "正文"}])

            with pytest.raises(RenderFailedException) as exc_info:
                await run_render(task, render_step, db_session, sse)

        assert exc_info.value.error_code == "E3107"


# ═══════════════════════════════════════════════════════════════
# 引用格式规范化
# ═══════════════════════════════════════════════════════════════


class TestCitationNormalization:
    """LLM 引用格式变体统一规范化为独立 [来源N]。"""

    def test_合并引用拆分为独立锚点(self):
        """[来源0,1] / [来源0, 1] / [来源0，1] 拆为 [来源0][来源1]。"""
        content = "参见[来源0,1]与[来源0，1]以及[来源0, 1]。"
        assert normalize_citation_markup(content) == "参见[来源0][来源1]与[来源0][来源1]以及[来源0][来源1]。"

    def test_短横线连接引用拆分为独立锚点(self):
        """[来源0-1] 拆为 [来源0][来源1]。"""
        assert normalize_citation_markup("参见[来源0-1]。") == "参见[来源0][来源1]。"

    def test_来源与数字间空格去除(self):
        """[来源 0] / [来源 0, 1] 去空格并拆分。"""
        content = "参见[来源 0]与[来源 0, 1]。"
        assert normalize_citation_markup(content) == "参见[来源0]与[来源0][来源1]。"

    def test_保守修正1based索引(self):
        """evidence 总数为 2 且最大值为 2 时，判定为 1-based 并减 1。"""
        content = "参见[来源1,2]。"
        assert normalize_citation_markup(content, valid_count=2) == "参见[来源0][来源1]。"

    def test_0based索引不因valid_count误判(self):
        """evidence 总数为 3 时，[来源0,1] 保持 0-based 不变。"""
        content = "参见[来源0,1]。"
        assert normalize_citation_markup(content, valid_count=3) == "参见[来源0][来源1]。"

    def test_1based修正要求所有索引大于等于1(self):
        """包含 0 时不触发 1-based 修正。"""
        content = "参见[来源0,2]。"
        assert normalize_citation_markup(content, valid_count=2) == "参见[来源0][来源2]。"

    def test_无valid_count时不做1based修正(self):
        """valid_count 为 None 时保持原数字。"""
        content = "参见[来源1,2]。"
        assert normalize_citation_markup(content) == "参见[来源1][来源2]。"

    @pytest.mark.asyncio
    async def test_合并引用在parse_render_output中被规范化(self, db_session):
        """Render 输出中的 [来源0,1] 会被拆分并正确建立 section_evidence。"""
        task, render_step, _ = await _seed_render_task(db_session, evidence_count=2)
        sse = AsyncMock()
        sections = [
            {
                "heading": "1. 合并引用",
                "content": "量子计算威胁[来源0,1]。",
            }
        ]

        with patch("app.pipeline.renderer.chat_completion") as mock_llm:
            mock_llm.return_value = _mock_llm_report(sections)
            output = await run_render(task, render_step, db_session, sse)

        assert output["citations_count"] == 2

        stmt = select(ReportSection).where(ReportSection.task_id == task.id)
        result = await db_session.execute(stmt)
        report_section = result.scalar_one()
        assert report_section.content == "量子计算威胁[来源0][来源1]。"

        stmt = select(SectionEvidence).where(SectionEvidence.section_id == report_section.id)
        result = await db_session.execute(stmt)
        associations = list(result.scalars().all())
        assert len(associations) == 2
