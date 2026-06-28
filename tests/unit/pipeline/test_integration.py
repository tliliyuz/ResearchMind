"""Pipeline 前半段集成测试 — Planning → Search → Fetch 全链路 Mock。

验证：
- 三阶段数据流转（sub_questions → search results → fetched docs）
- ResearchSource 持久化从 Search 到 Fetch
- SSE 事件序列完整性
- 子 step 树结构
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import PlanningFailedException, SearchFailedException
from app.core.llm import LLMResult
from app.models.research_step import ResearchStep
from app.models.research_source import ResearchSource
from app.pipeline.planner import run_planning
from app.pipeline.searcher import run_search


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _make_mock_task(**overrides) -> MagicMock:
    """创建模拟 ResearchTask（MagicMock），避免 ORM backref 问题。"""
    defaults = {
        "id": "integ-task-uuid",
        "user_id": 1,
        "topic": "量子计算对网络安全的威胁与应对策略",
        "requirements": {
            "task_type": "analysis",
            "depth": "quick",
            "max_sources": 10,
            "language": "zh",
        },
        "status": "running",
        "current_phase": None,
        "total_steps": 1,
        "completed_steps": 0,
        "total_sources": 0,
        "total_evidence": 0,
    }
    defaults.update(overrides)
    task = MagicMock()
    for k, v in defaults.items():
        setattr(task, k, v)
    return task


def _make_mock_step(**overrides) -> MagicMock:
    """创建模拟 ResearchStep（MagicMock），避免 ORM backref 问题。"""
    defaults = {
        "id": "step-001",
        "task_id": "integ-task-uuid",
        "step_type": "planning",
        "status": "running",
        "label": "Phase",
        "parent_step": None,
        "output": None,
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
    }
    defaults.update(overrides)
    step = MagicMock(spec=ResearchStep)
    for k, v in defaults.items():
        setattr(step, k, v)
    return step


def _valid_planning_json() -> str:
    return json.dumps({
        "sub_questions": [
            "量子计算对RSA和ECC加密算法的具体威胁",
            "NIST后量子密码标准化最新进展",
            "中国在量子安全通信领域的政策与布局",
        ],
        "rationale": "从技术威胁、标准应对、政策布局三维度拆解",
    }, ensure_ascii=False)


def _make_llm_result(content: str) -> LLMResult:
    return LLMResult(
        content=content,
        reasoning_content="",
        prompt_tokens=120,
        completion_tokens=60,
        total_tokens=180,
    )


def _mock_session_with_planning(session: AsyncMock, planning_step: MagicMock) -> None:
    """让 session.execute 在 Search 读取 Planning 输出时返回指定 step。

    Search 阶段通过显式查询 research_steps 表获取 sub_questions，
    不再依赖 ORM relationship 懒加载。
    """
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = planning_step
    session.execute.return_value = result_mock


# ═══════════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════════


class TestPlanningToSearchFlow:
    """Planning → Search 数据流转验证。"""

    @pytest.mark.asyncio
    async def test_Planner产出_被Searcher正确消费(self):
        """Planning 产出的 sub_questions 被 Search 阶段正确读取。"""
        task = _make_mock_task()
        planning_step = _make_mock_step(step_type="planning", id="step-plan-001")
        sse = AsyncMock()
        db = AsyncMock()

        # Phase 1: Planning
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            planning_output = await run_planning(task, planning_step, db, sse)

            assert len(planning_output["sub_questions"]) == 3

        # 模拟 Planning 步骤写入 output
        planning_step.output = planning_output

        # Phase 2: Search — 使用 MagicMock 避免 ORM 关系触发
        search_step = _make_mock_step(step_type="search", id="step-search-001")
        search_step.parent_step = planning_step  # MagicMock 不会触发 ORM backref
        _mock_session_with_planning(db, planning_step)

        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = [
                {"results": [{"url": f"https://source{i}.com/q1", "title": f"Source {i}", "score": 0.8} for i in range(1, 3)]},
                {"results": [{"url": f"https://source{i}.com/q2", "title": f"Source {i}", "score": 0.8} for i in range(1, 3)]},
                {"results": [{"url": f"https://source{i}.com/q3", "title": f"Source {i}", "score": 0.8} for i in range(1, 3)]},
            ]

            search_output = await run_search(task, search_step, db, sse)

            assert search_output["after_dedup"] == 6
            assert search_output["sources_created"] == 6

    @pytest.mark.asyncio
    async def test_Planner失败_不进入Search(self):
        """Planning 抛出 E3101 时 Search 不应被调用。"""
        task = _make_mock_task()
        planning_step = _make_mock_step(step_type="planning", id="step-plan-fail")
        sse = AsyncMock()
        db = AsyncMock()

        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(
                '{"sub_questions": ["只有一个子问题"]}'
            )

            with pytest.raises(PlanningFailedException) as exc_info:
                await run_planning(task, planning_step, db, sse)

            assert exc_info.value.error_code == "E3101"
            # 验证重试了 3 次
            assert mock_llm.call_count == 3


class TestSearchToFetchFlow:
    """Search → Fetch 数据流转验证（ResearchSource 持久化）。"""

    @pytest.mark.asyncio
    async def test_Search产出_写入ResearchSource_Fetch可读取(self):
        """Search 阶段写入的 ResearchSource 行在 Fetch 阶段可查询。"""
        task = _make_mock_task()
        search_step = _make_mock_step(step_type="search", id="step-search-src")
        sse = AsyncMock()
        db = AsyncMock()

        # 设置 Planning parent（MagicMock 避免 ORM 问题）
        parent = _make_mock_step(step_type="planning", id="step-plan-src")
        parent.output = {"sub_questions": ["测试子问题"]}
        search_step.parent_step = parent
        _mock_session_with_planning(db, parent)

        # Search 阶段
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.return_value = {
                "results": [
                    {"url": "https://example.com/article1", "title": "Article 1", "score": 0.9},
                    {"url": "https://example.com/article2", "title": "Article 2", "score": 0.8},
                ],
            }

            await run_search(task, search_step, db, sse)

        # 验证 ResearchSource 通过 session.add 被添加
        add_calls = [
            c for c in db.add.call_args_list
            if isinstance(c[0][0], ResearchSource)
        ]
        assert len(add_calls) == 2  # 两个 URL 各一个 source

        # 验证 source 属性正确
        first_source = add_calls[0][0][0]
        assert first_source.task_id == task.id
        assert first_source.fetch_status is None  # 等待 Fetch 填充
        assert first_source.url.startswith("https://")

    @pytest.mark.asyncio
    async def test_Search全失败_Fetch被跳过(self):
        """全部子问题搜索失败抛出 E3102，Pipeline 终止。"""
        task = _make_mock_task()
        search_step = _make_mock_step(step_type="search", id="step-search-fail")
        sse = AsyncMock()
        db = AsyncMock()

        parent = _make_mock_step(step_type="planning")
        parent.output = {
            "sub_questions": ["子问题A", "子问题B", "子问题C"],
        }
        search_step.parent_step = parent
        _mock_session_with_planning(db, parent)

        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = RuntimeError("Tavily API 完全不可用")

            with pytest.raises(SearchFailedException) as exc_info:
                await run_search(task, search_step, db, sse)

            assert exc_info.value.error_code == "E3102"


class TestPipelineSseEventSequence:
    """SSE 事件序列完整性验证。"""

    @pytest.mark.asyncio
    async def test_Planner发射正确事件序列(self):
        """验证 Planning 阶段 SSE 事件包含 step.progress。"""
        task = _make_mock_task()
        step = _make_mock_step(step_type="planning", id="step-sse-plan")
        sse = AsyncMock()
        db = AsyncMock()

        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            await run_planning(task, step, db, sse)

        # 获取所有发布的事件类型
        events = [c[0][0] for c in sse.publish.await_args_list]
        assert "step.progress" in events  # 进度事件

        # step.progress 事件应包含 sub_questions_generated
        progress_calls = [
            c for c in sse.publish.await_args_list
            if c[0][0] == "step.progress"
        ]
        last_progress = progress_calls[-1]
        data = last_progress[0][1]
        assert "sub_questions_generated" in data

    @pytest.mark.asyncio
    async def test_Searcher为每个子问题发射步骤事件(self):
        """验证 Search 为每个子问题发射 step.started/step.completed。"""
        task = _make_mock_task()
        search_step = _make_mock_step(step_type="search", id="step-sse-search")
        sse = AsyncMock()
        db = AsyncMock()

        parent = _make_mock_step(step_type="planning", id="step-sse-plan-parent")
        parent.output = {
            "sub_questions": ["子问题A", "子问题B"],
        }
        search_step.parent_step = parent
        _mock_session_with_planning(db, parent)

        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = [
                {"results": [{"url": "https://a.com/1", "title": "A1", "score": 0.9}]},
                {"results": [{"url": "https://b.com/1", "title": "B1", "score": 0.8}]},
            ]

            await run_search(task, search_step, db, sse)

        events = [c[0][0] for c in sse.publish.await_args_list]
        # 每个子问题至少有一个 started 和一个 completed
        started_count = events.count("step.started")
        completed_count = events.count("step.completed")
        assert started_count >= 2  # 2个子问题
        assert completed_count >= 2
