"""Searcher 单元测试 — Tavily API 调用、子 step 管理、URL 去重、失败重试。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import SearchFailedException
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.research_source import ResearchSource
from app.pipeline.searcher import (
    run_search,
    _extract_domain,
    _load_sub_questions,
)


# ═══════════════════════════════════════════════════════════════
# 工具函数测试
# ═══════════════════════════════════════════════════════════════


class TestExtractDomain:
    """域名提取。"""

    def test_标准URL提取域名(self):
        assert _extract_domain("https://example.com/page") == "example.com"

    def test_含端口URL(self):
        assert _extract_domain("http://localhost:8080/path") == "localhost:8080"

    def test_无效URL返回原文(self):
        assert _extract_domain("not-a-url") == "not-a-url"


def _make_planning_step(sub_questions: list[str]) -> MagicMock:
    """创建模拟 Planning Step（用于 _load_sub_questions）。"""
    step = MagicMock(spec=ResearchStep)
    step.output = {"sub_questions": sub_questions}
    step.status = "completed"
    step.completed_at = None
    return step


class TestLoadSubQuestions:
    """从 Planning 输出中异步读取 sub_questions。"""

    def _setup_session(self, planning_step: MagicMock | None) -> AsyncMock:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = planning_step
        session.execute.return_value = result_mock
        return session

    @pytest.mark.asyncio
    async def test_正常提取(self):
        task = MagicMock(spec=ResearchTask)
        task.id = "task-uuid-001"
        session = self._setup_session(_make_planning_step(["q1", "q2", "q3"]))

        result = await _load_sub_questions(session, task)
        assert result == ["q1", "q2", "q3"]

    @pytest.mark.asyncio
    async def test_无PlanningStep(self):
        task = MagicMock(spec=ResearchTask)
        task.id = "task-uuid-001"
        session = self._setup_session(None)

        result = await _load_sub_questions(session, task)
        assert result == []

    @pytest.mark.asyncio
    async def test_planning_output为None(self):
        task = MagicMock(spec=ResearchTask)
        task.id = "task-uuid-001"
        planning_step = _make_planning_step(["q1"])
        planning_step.output = None
        session = self._setup_session(planning_step)

        result = await _load_sub_questions(session, task)
        assert result == []

    @pytest.mark.asyncio
    async def test_planning_output无sub_questions(self):
        task = MagicMock(spec=ResearchTask)
        task.id = "task-uuid-001"
        planning_step = _make_planning_step(["q1"])
        planning_step.output = {"other": "data"}
        session = self._setup_session(planning_step)

        result = await _load_sub_questions(session, task)
        assert result == []


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _make_task(**overrides) -> MagicMock:
    """创建模拟 ResearchTask（MagicMock），避免 ORM backref 问题。"""
    defaults = {
        "id": "task-uuid-001",
        "user_id": 1,
        "topic": "量子计算",
        "requirements": {"task_type": "analysis", "max_sources": 10},
        "status": "running",
        "current_phase": "searching",
        "total_steps": 2,
        "completed_steps": 1,
        "total_sources": 0,
        "total_evidence": 0,
    }
    defaults.update(overrides)
    task = MagicMock()
    for k, v in defaults.items():
        setattr(task, k, v)
    return task


def _make_step(**overrides) -> MagicMock:
    """创建模拟 ResearchStep（MagicMock），避免 ORM backref 问题。"""
    defaults = {
        "id": "step-uuid-search-root",
        "task_id": "task-uuid-001",
        "step_type": "search",
        "status": "running",
        "label": "Search：多子问题搜索",
    }
    defaults.update(overrides)
    step = MagicMock(spec=ResearchStep)
    for k, v in defaults.items():
        setattr(step, k, v)
    return step


def _make_tavily_response(urls: list[str]) -> dict:
    """构建模拟 Tavily API 返回（包装在 dict 中）。"""
    return {
        "results": [
            {
                "url": url,
                "title": f"Title for {url}",
                "content": f"Content snippet for {url}",
                "score": 0.9 - i * 0.05,
            }
            for i, url in enumerate(urls)
        ],
        "query": "test query",
    }


def _mock_planning_in_session(session: AsyncMock, sub_questions: list[str]) -> None:
    """让 session.execute 返回包含指定 sub_questions 的 Planning Step。"""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = _make_planning_step(sub_questions)
    session.execute.return_value = result_mock


# ═══════════════════════════════════════════════════════════════
# run_search 正常流程
# ═══════════════════════════════════════════════════════════════


class TestRunSearchSuccess:
    """正常搜索流程。"""

    DEFAULT_SUB_QUESTIONS = [
        "量子计算对密码学的威胁",
        "后量子密码标准化进展",
        "NIST后量子密码竞赛结果",
    ]

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task = _make_task()
        self.step = _make_step()
        self.sse_bridge = AsyncMock()
        self.db_session = AsyncMock()
        _mock_planning_in_session(self.db_session, self.DEFAULT_SUB_QUESTIONS)

    @pytest.mark.asyncio
    async def test_正常搜索_返回去重结果(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            # 每个子问题返回2条结果
            mock_tavily.side_effect = [
                _make_tavily_response(["https://a.com/1", "https://a.com/2"]),
                _make_tavily_response(["https://b.com/1", "https://b.com/2"]),
                _make_tavily_response(["https://c.com/1", "https://c.com/2"]),
            ]

            output = await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert output["after_dedup"] == 6
            assert output["sources_created"] == 6
            assert mock_tavily.call_count == 3

    @pytest.mark.asyncio
    async def test_跨子问题URL去重(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = [
                _make_tavily_response(["https://a.com/1", "https://shared.com/page"]),
                _make_tavily_response(["https://shared.com/page", "https://b.com/1"]),
                _make_tavily_response(["https://c.com/1"]),
            ]

            output = await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            # shared.com/page 被去重，所以只有 4 条唯一 URL
            assert output["after_dedup"] == 4

    @pytest.mark.asyncio
    async def test_搜索后创建_ResearchSource_行(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.return_value = _make_tavily_response(["https://example.com/article"])

            await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            # 验证 session.add 被调用（创建 ResearchSource）
            add_calls = [
                c for c in self.db_session.add.call_args_list
                if isinstance(c[0][0], ResearchSource)
            ]
            assert len(add_calls) == 1  # 每个 URL 一个 source

    @pytest.mark.asyncio
    async def test_子_step_SSE_事件已发射(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.return_value = _make_tavily_response(["https://example.com/1"])

            await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            # 验证发射了 step.started / step.progress / step.completed
            event_types = [
                c[0][0] for c in self.sse_bridge.publish.await_args_list
            ]
            assert "step.started" in event_types
            assert "step.progress" in event_types
            assert "step.completed" in event_types

    @pytest.mark.asyncio
    async def test_创建子step不递增task_total_steps(self):
        """子 step 不应影响全局进度分母，task.total_steps 保持不变。"""
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = [
                _make_tavily_response(["https://a.com/1"]),
                _make_tavily_response(["https://b.com/1"]),
                _make_tavily_response(["https://c.com/1"]),
            ]

            original_total = self.task.total_steps
            await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert self.task.total_steps == original_total

    @pytest.mark.asyncio
    async def test_无子问题输入_返回空结果(self):
        # 让 Planning 输出空子问题
        _mock_planning_in_session(self.db_session, [])

        output = await run_search(
            self.task, self.step, self.db_session, self.sse_bridge,
        )

        assert output["total_results"] == 0
        assert "无子问题输入" in output["message"]


class TestRunSearchFailure:
    """失败策略：单子问题降级 / 全失败 E3102。"""

    DEFAULT_SUB_QUESTIONS = [
        "量子计算对密码学的威胁",
        "后量子密码标准化进展",
        "NIST后量子密码竞赛结果",
    ]

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task = _make_task()
        self.step = _make_step()
        self.sse_bridge = AsyncMock()
        self.db_session = AsyncMock()
        _mock_planning_in_session(self.db_session, self.DEFAULT_SUB_QUESTIONS)

    @pytest.mark.asyncio
    async def test_单子问题0结果_子step_SKIPPED(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = [
                {"results": []},  # 子问题1: 0结果
                _make_tavily_response(["https://b.com/1"]),  # 子问题2
                _make_tavily_response(["https://c.com/1"]),  # 子问题3
            ]

            output = await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            # 子问题1 应标记为 skipped
            sq1_result = output["sub_question_results"][0]
            assert sq1_result["status"] == "skipped"
            assert output["after_dedup"] == 2  # 去重后结果数

    @pytest.mark.asyncio
    async def test_全部子问题失败_抛出E3102(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            # 全部失败
            mock_tavily.side_effect = RuntimeError("API不可用")

            with pytest.raises(SearchFailedException) as exc_info:
                await run_search(
                    self.task, self.step, self.db_session, self.sse_bridge,
                )

            assert exc_info.value.error_code == "E3102"

    @pytest.mark.asyncio
    async def test_子问题失败后重试(self):
        with patch("app.pipeline.searcher._call_tavily") as mock_tavily:
            mock_tavily.side_effect = [
                RuntimeError("第一次失败"),
                _make_tavily_response(["https://recovered.com/1"]),  # 重试成功
            ]
            # 只保留1个子问题来测试重试
            _mock_planning_in_session(self.db_session, ["单个子问题"])

            output = await run_search(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert mock_tavily.call_count == 2  # 原始 + 1次重试
            assert output["after_dedup"] == 1
