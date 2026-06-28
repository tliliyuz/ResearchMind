"""Evidence Graph Build 阶段单元测试 —— 结构化认知资产组装。"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.core.exceptions import EvidenceGraphBuildFailedException
from app.models.evidence_item import EvidenceItem
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.models.user import User
from app.pipeline.evidence_graph import run_evidence_graph
from app.pipeline.sse_bridge import EVENT_STEP_PROGRESS


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _valid_synthesis_output(
    supporting_indices: list[int] | None = None,
    conflicting_indices: list[int] | None = None,
) -> dict:
    """生成有效 Synthesis output JSON。"""
    return {
        "clusters": [
            {
                "theme": "量子计算威胁",
                "summary": "量子计算对 RSA 和 ECC 构成实际威胁。",
                "consensus_level": "strong",
                "supporting_evidence_indices": supporting_indices or [0, 1],
                "conflicting_evidence_indices": conflicting_indices or [],
            }
        ],
        "conflicts": [
            {
                "topic": "标准化时间表分歧",
                "position_a": {"summary": "NIST 2024 年发布最终标准", "evidence_indices": [0]},
                "position_b": {"summary": "业界认为需更长时间验证", "evidence_indices": [1]},
            }
        ],
        "knowledge_gaps": ["量子计算机实际错误率数据"],
        "overall_assessment": "证据质量较高，但缺少具体量化数据。",
    }


async def _seed_evidence_graph_task(
    db_session,
    max_sources: int = 10,
    evidence_count: int = 3,
    evidence_contents: list[str] | None = None,
    relevance_scores: list[float] | None = None,
    source_domains: list[str] | None = None,
    synthesis_output: dict | None = None,
    task_suffix: str = "001",
) -> tuple[ResearchTask, ResearchStep]:
    """在测试数据库中预置一个可进入 Evidence Graph Build 的任务。

    Returns:
        (task, evidence_graph_step)
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
        id=f"task-eg-{task_suffix}",
        user_id=1,
        topic="量子计算对密码学的影响",
        requirements={
            "task_type": "analysis",
            "depth": "quick",
            "max_sources": max_sources,
            "language": "zh",
        },
        status="running",
        total_steps=5,
        completed_steps=4,
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
    domains = source_domains or ["example.com", "nist.gov", "example.com"]

    for i in range(evidence_count):
        source = ResearchSource(
            task_id=task.id,
            url=f"https://{domains[i]}/source-{i}",
            title=f"来源 {i}",
            domain=domains[i],
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
        status="completed",
        label="Synthesis",
        output=synthesis_output or _valid_synthesis_output(),
        started_at=datetime(2026, 1, 1, 0, 0, 4, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc),
        duration_ms=1000,
    )
    db_session.add(synthesis_step)

    evidence_graph_step = ResearchStep(
        id=f"step-eg-{task_suffix}",
        task_id=task.id,
        step_type="evidence_graph",
        status="running",
        label="Evidence Graph",
        started_at=datetime(2026, 1, 1, 0, 0, 6, tzinfo=timezone.utc),
    )
    db_session.add(evidence_graph_step)

    await db_session.flush()
    return task, evidence_graph_step


# ═══════════════════════════════════════════════════════════════
# 成功路径
# ═══════════════════════════════════════════════════════════════


class TestEvidenceGraphSuccess:
    """Evidence Graph Build 正常流程。"""

    @pytest.mark.asyncio
    async def test_正常构建Graph_output结构完整(self, db_session):
        """正常构建产出完整 graph 字段，SSE 发射 step.progress。"""
        task, eg_step = await _seed_evidence_graph_task(db_session, evidence_count=2)
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        graph = output["graph"]
        assert graph["task_id"] == task.id
        assert "generated_at" in graph
        assert isinstance(graph["items"], list)
        assert isinstance(graph["clusters"], list)
        assert isinstance(graph["conflicts"], list)
        assert isinstance(graph["knowledge_gaps"], list)
        assert isinstance(graph["sources"], list)

        assert output["item_count"] == 2
        assert output["cluster_count"] == 1
        assert output["conflict_count"] == 1
        assert output["source_count"] == 2
        assert isinstance(output["duration_ms"], int)

        progress_calls = [c for c in sse.publish.await_args_list if c.args[0] == EVENT_STEP_PROGRESS]
        assert len(progress_calls) == 2
        assert progress_calls[0].args[1]["label"] == "正在构建来源图谱..."
        assert progress_calls[1].args[1]["item_count"] == 2
        assert progress_calls[1].args[1]["cluster_count"] == 1
        assert "来源图谱构建完成" in progress_calls[1].args[1]["label"]

    @pytest.mark.asyncio
    async def test_items按relevance_score降序并重新分配index(self, db_session):
        """高 relevance_score 排在前面且 index 为 0。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=3,
            relevance_scores=[0.75, 0.95, 0.85],
            synthesis_output=_valid_synthesis_output(supporting_indices=[0, 1, 2]),
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        items = output["graph"]["items"]
        assert len(items) == 3
        assert items[0]["index"] == 0
        assert items[0]["relevance_score"] == 0.95
        assert items[1]["index"] == 1
        assert items[1]["relevance_score"] == 0.85
        assert items[2]["index"] == 2
        assert items[2]["relevance_score"] == 0.75

    @pytest.mark.asyncio
    async def test_cluster信息写回items(self, db_session):
        """supporting indices 正确反写 cluster_theme / consensus_level。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            synthesis_output=_valid_synthesis_output(supporting_indices=[0, 1]),
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        items = output["graph"]["items"]
        assert items[0]["cluster_theme"] == "量子计算威胁"
        assert items[0]["consensus_level"] == "strong"
        assert items[1]["cluster_theme"] == "量子计算威胁"
        assert items[1]["consensus_level"] == "strong"

    @pytest.mark.asyncio
    async def test_conflicting_evidence_indices也参与写回(self, db_session):
        """conflicting indices 在 supporting 未覆盖时 fallback 写入。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            synthesis_output=_valid_synthesis_output(
                supporting_indices=[0],
                conflicting_indices=[1],
            ),
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        items = output["graph"]["items"]
        assert items[0]["cluster_theme"] == "量子计算威胁"
        assert items[1]["cluster_theme"] == "量子计算威胁"

    @pytest.mark.asyncio
    async def test_sources聚合统计evidence_count(self, db_session):
        """同一 source 贡献多条 evidence 时计数正确。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            source_domains=["example.com", "nist.gov"],
            synthesis_output=_valid_synthesis_output(supporting_indices=[0, 1]),
        )

        # 让 source-0 再贡献一条 evidence
        source0 = (await db_session.execute(
            select(ResearchSource).where(
                ResearchSource.task_id == task.id,
                ResearchSource.domain == "example.com",
            )
        )).scalar_one()
        extra_ev = EvidenceItem(
            task_id=task.id,
            source_id=source0.id,
            step_id=(await db_session.execute(
                select(ResearchStep).where(
                    ResearchStep.task_id == task.id,
                    ResearchStep.step_type == "rerank",
                )
            )).scalar_one().id,
            content="额外的证据片段，同样来自 example.com。",
            relevance_score=0.88,
        )
        db_session.add(extra_ev)
        await db_session.flush()

        sse = AsyncMock()
        output = await run_evidence_graph(task, eg_step, db_session, sse)

        sources = output["graph"]["sources"]
        # example.com 贡献 2 条，nist.gov 贡献 1 条；按 evidence_count 降序
        assert sources[0]["domain"] == "example.com"
        assert sources[0]["evidence_count"] == 2
        assert sources[1]["domain"] == "nist.gov"
        assert sources[1]["evidence_count"] == 1

    @pytest.mark.asyncio
    async def test_used_in_sections初始为空数组(self, db_session):
        """所有 items 的 used_in_sections 初始为空数组。"""
        task, eg_step = await _seed_evidence_graph_task(db_session, evidence_count=2)
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        for item in output["graph"]["items"]:
            assert item["used_in_sections"] == []

    @pytest.mark.asyncio
    async def test_knowledge_gaps和conflicts透传(self, db_session):
        """knowledge_gaps 和 conflicts 从 Synthesis output 透传。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            synthesis_output={
                "clusters": [
                    {
                        "theme": "测试",
                        "summary": "测试摘要",
                        "consensus_level": "moderate",
                        "supporting_evidence_indices": [0],
                        "conflicting_evidence_indices": [],
                    }
                ],
                "conflicts": [
                    {
                        "topic": "分歧 A",
                        "position_a": {"summary": "立场 1", "evidence_indices": [0]},
                        "position_b": {"summary": "立场 2", "evidence_indices": []},
                    }
                ],
                "knowledge_gaps": ["缺口 1", "缺口 2"],
                "overall_assessment": "测试评估",
            },
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        assert output["graph"]["knowledge_gaps"] == ["缺口 1", "缺口 2"]
        assert output["graph"]["conflicts"][0]["topic"] == "分歧 A"
        assert output["conflict_count"] == 1

    @pytest.mark.asyncio
    async def test_max_sources截断Evidence数量(self, db_session):
        """max_sources=2 截断 4 条 evidence。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            max_sources=2,
            evidence_count=4,
            relevance_scores=[0.9, 0.8, 0.7, 0.6],
            source_domains=["example.com", "nist.gov", "arxiv.org", "blog.org"],
            synthesis_output=_valid_synthesis_output(supporting_indices=[0, 1]),
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        assert output["item_count"] == 2
        assert len(output["graph"]["items"]) == 2
        assert output["graph"]["items"][0]["relevance_score"] == 0.9
        assert output["graph"]["items"][1]["relevance_score"] == 0.8


# ═══════════════════════════════════════════════════════════════
# 失败路径
# ═══════════════════════════════════════════════════════════════


class TestEvidenceGraphFailure:
    """Evidence Graph Build 失败策略。"""

    @pytest.mark.asyncio
    async def test_缺少Evidence抛出E3106(self, db_session):
        """没有 EvidenceItem 时抛出 E3106。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=0,
        )
        sse = AsyncMock()

        with pytest.raises(EvidenceGraphBuildFailedException) as exc_info:
            await run_evidence_graph(task, eg_step, db_session, sse)

        assert exc_info.value.error_code == "E3106"
        assert "EvidenceItem" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_缺少SynthesisOutput抛出E3106(self, db_session):
        """Synthesis Step output 为空时抛出 E3106。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            synthesis_output={"clusters": []},
        )

        # 清空 synthesis output
        synthesis_step = (await db_session.execute(
            select(ResearchStep).where(
                ResearchStep.task_id == task.id,
                ResearchStep.step_type == "synthesis",
            )
        )).scalar_one()
        synthesis_step.output = None
        await db_session.flush()

        sse = AsyncMock()
        with pytest.raises(EvidenceGraphBuildFailedException) as exc_info:
            await run_evidence_graph(task, eg_step, db_session, sse)

        assert exc_info.value.error_code == "E3106"
        assert "Synthesis" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_cluster越界索引被过滤不阻断(self, db_session):
        """cluster supporting indices 越界时被过滤，不阻断构建。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            synthesis_output=_valid_synthesis_output(supporting_indices=[0, 1, 999]),
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        cluster = output["graph"]["clusters"][0]
        assert cluster["evidence_indices"] == [0, 1]
        assert output["item_count"] == 2

    @pytest.mark.asyncio
    async def test_conflict越界索引被过滤(self, db_session):
        """conflict position 中的越界索引被过滤。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            synthesis_output={
                "clusters": [
                    {
                        "theme": "测试",
                        "summary": "测试摘要",
                        "consensus_level": "moderate",
                        "supporting_evidence_indices": [0],
                        "conflicting_evidence_indices": [],
                    }
                ],
                "conflicts": [
                    {
                        "topic": "分歧",
                        "position_a": {"summary": "立场 1", "evidence_indices": [0, 999]},
                        "position_b": {"summary": "立场 2", "evidence_indices": [1, -1]},
                    }
                ],
                "knowledge_gaps": [],
                "overall_assessment": "测试",
            },
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        conflict = output["graph"]["conflicts"][0]
        assert conflict["position_a"]["evidence_indices"] == [0]
        assert conflict["position_b"]["evidence_indices"] == [1]


# ═══════════════════════════════════════════════════════════════
# 一致性
# ═══════════════════════════════════════════════════════════════


class TestEvidenceGraphConsistency:
    """Evidence Graph Build 一致性校验。"""

    @pytest.mark.asyncio
    async def test_GraphIndex与EvidenceItemId不同(self, db_session):
        """Graph index 是 0-based 排序位置，与 EvidenceItem.id 不同。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=2,
            relevance_scores=[0.9, 0.8],
            synthesis_output=_valid_synthesis_output(supporting_indices=[0, 1]),
        )
        sse = AsyncMock()

        output = await run_evidence_graph(task, eg_step, db_session, sse)

        items = output["graph"]["items"]
        # 查询实际 EvidenceItem.id（自增，通常 ≥1）
        result = await db_session.execute(
            select(EvidenceItem).where(EvidenceItem.task_id == task.id)
            .order_by(
                sa.case((EvidenceItem.relevance_score == None, 1), else_=0),
                EvidenceItem.relevance_score.desc(),
            )
        )
        evidence_items = list(result.scalars().all())

        assert items[0]["index"] == 0
        assert evidence_items[0].id != 0
        assert items[0]["index"] != evidence_items[0].id

    @pytest.mark.asyncio
    async def test_source关系为空时fallback到source_id(self, db_session):
        """source 关系存在但字段为空时，source_id 仍正确保留，字段 fallback 为空字符串。"""
        task, eg_step = await _seed_evidence_graph_task(
            db_session,
            evidence_count=1,
            source_domains=["example.com"],
            synthesis_output={
                "clusters": [
                    {
                        "theme": "测试",
                        "summary": "测试摘要",
                        "consensus_level": "weak",
                        "supporting_evidence_indices": [0],
                        "conflicting_evidence_indices": [],
                    }
                ],
                "conflicts": [],
                "knowledge_gaps": [],
                "overall_assessment": "测试",
            },
        )

        # 将 source 的 title / domain 置空，模拟 source 字段缺失
        source = (await db_session.execute(
            select(ResearchSource).where(ResearchSource.task_id == task.id)
        )).scalar_one()
        source.title = None
        source.domain = None
        await db_session.flush()

        sse = AsyncMock()
        output = await run_evidence_graph(task, eg_step, db_session, sse)

        item = output["graph"]["items"][0]
        assert item["source_id"] == source.id
        assert item["source_url"] == source.url
        assert item["source_title"] == ""
        assert item["domain"] == ""
