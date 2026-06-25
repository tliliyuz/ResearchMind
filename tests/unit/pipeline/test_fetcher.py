"""Fetcher 单元测试 — HTTP 抓取、trafilatura 提取、SSRF 防护、ResearchSource 更新。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.research_source import ResearchSource
from app.pipeline.fetcher import (
    run_fetch,
    _check_url_safety,
    _extract_domain,
    _extract_title_from_content,
)


# ═══════════════════════════════════════════════════════════════
# URL 安全检查测试
# ═══════════════════════════════════════════════════════════════


class TestCheckUrlSafety:
    """URL 安全检查：协议白名单 + IP 黑名单 SSRF 防护。

    注：_check_url_safety 为私有函数，测试保留以覆盖 SSRF 安全关键路径。
    Phase3 后应通过 run_fetch 公共 API 间接覆盖。
    """

    @pytest.mark.asyncio
    async def test_https通过(self):
        assert await _check_url_safety("https://example.com/page") is None

    @pytest.mark.asyncio
    async def test_http通过(self):
        assert await _check_url_safety("http://example.com/page") is None

    @pytest.mark.asyncio
    async def test_file协议拒绝(self):
        result = await _check_url_safety("file:///etc/passwd")
        assert result is not None
        assert "file" in result

    @pytest.mark.asyncio
    async def test_ftp协议拒绝(self):
        result = await _check_url_safety("ftp://example.com/file")
        assert result is not None
        assert "ftp" in result

    @pytest.mark.asyncio
    async def test_localhost_127_拒绝(self):
        result = await _check_url_safety("http://127.0.0.1:8080/admin")
        assert result is not None
        assert "内网" in result or "拒绝" in result

    @pytest.mark.asyncio
    async def test_10段内网IP拒绝(self):
        result = await _check_url_safety("http://10.0.0.1/api")
        assert result is not None
        assert "内网" in result or "拒绝" in result

    @pytest.mark.asyncio
    async def test_192_168段内网IP拒绝(self):
        result = await _check_url_safety("http://192.168.1.1/admin")
        assert result is not None
        assert "内网" in result or "拒绝" in result

    @pytest.mark.asyncio
    async def test_172_16段内网IP拒绝(self):
        result = await _check_url_safety("http://172.16.0.1/api")
        assert result is not None

    @pytest.mark.asyncio
    async def test_URL缺少hostname(self):
        result = await _check_url_safety("http:///path-only")
        assert result is not None


# ═══════════════════════════════════════════════════════════════
# 工具函数测试
# ═══════════════════════════════════════════════════════════════


class TestExtractDomain:
    def test_标准域名(self):
        assert _extract_domain("https://www.example.com/page?a=1") == "www.example.com"

    def test_无效URL(self):
        assert _extract_domain("invalid") == "invalid"


class TestExtractTitleFromContent:
    def test_从H1标题提取(self):
        content = "# 这是一篇关于量子计算的文章\n\n正文内容..."
        title = _extract_title_from_content(content, "https://example.com")
        assert title == "这是一篇关于量子计算的文章"

    def test_无标题回退域名(self):
        content = "没有标题的正文内容"
        title = _extract_title_from_content(content, "https://example.com/page")
        assert title == "example.com"

    def test_空内容回退域名(self):
        title = _extract_title_from_content(None, "https://fallback.com")
        assert title == "fallback.com"


# ═══════════════════════════════════════════════════════════════
# 辅助工厂
# ═══════════════════════════════════════════════════════════════


def _make_task(**overrides) -> ResearchTask:
    defaults = {
        "id": "task-uuid-001",
        "user_id": 1,
        "topic": "量子计算",
        "requirements": {"task_type": "analysis"},
        "status": "running",
        "current_phase": "fetching",
        "total_steps": 3,
        "completed_steps": 2,
        "total_sources": 3,
        "total_evidence": 0,
    }
    defaults.update(overrides)
    return ResearchTask(**defaults)


def _make_step(**overrides) -> ResearchStep:
    defaults = {
        "id": "step-uuid-fetch-root",
        "task_id": "task-uuid-001",
        "step_type": "fetch",
        "status": "running",
        "label": "Fetch：网页内容抓取",
    }
    defaults.update(overrides)
    return ResearchStep(**defaults)


def _make_mock_sources(count: int = 3) -> list[MagicMock]:
    """创建模拟 ResearchSource 列表。"""
    sources = []
    urls = [
        "https://example.com/article1",
        "https://example.com/article2",
        "https://example.com/article3",
    ]
    for i in range(min(count, len(urls))):
        src = MagicMock(spec=ResearchSource)
        src.id = 100 + i
        src.url = urls[i]
        src.fetch_status = None
        sources.append(src)
    return sources


def _make_fetch_success_result() -> dict:
    return {
        "status": "success",
        "content": "# Test Article\n\nThis is the content of the test article.",
        "content_length": 58,
        "error": None,
    }


def _make_fetch_timeout_result() -> dict:
    return {"status": "timeout", "content": None, "content_length": None,
            "error": "请求超时"}


def _make_fetch_blocked_result(status_code: int = 403) -> dict:
    return {"status": "blocked", "content": None, "content_length": None,
            "error": f"HTTP {status_code}"}


# ═══════════════════════════════════════════════════════════════
# run_fetch 正常流程
# ═══════════════════════════════════════════════════════════════


class TestRunFetchSuccess:
    """正常抓取流程。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task = _make_task()
        self.step = _make_step()
        self.sse_bridge = MagicMock()
        self.db_session = AsyncMock()

    @pytest.mark.asyncio
    async def test_正常抓取_更新_ResearchSource(self):
        mock_sources = _make_mock_sources(2)
        self.db_session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        self.db_session.execute.return_value = mock_result

        with patch("app.pipeline.fetcher._fetch_one_url") as mock_fetch:
            mock_fetch.return_value = _make_fetch_success_result()

            output = await run_fetch(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert output["successful"] == 2
            assert output["failed"] == 0
            assert self.task.total_sources == 2

    @pytest.mark.asyncio
    async def test_无待抓取URL_提前返回(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.db_session.execute = AsyncMock(return_value=mock_result)

        output = await run_fetch(
            self.task, self.step, self.db_session, self.sse_bridge,
        )

        assert output["successful"] == 0
        assert "无待抓取" in output["message"]

    @pytest.mark.asyncio
    async def test_子_step_SSE_事件已发射(self):
        mock_sources = _make_mock_sources(1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        self.db_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.pipeline.fetcher._fetch_one_url") as mock_fetch:
            mock_fetch.return_value = _make_fetch_success_result()

            await run_fetch(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            event_types = [
                c[0][0] for c in self.sse_bridge.publish.call_args_list
            ]
            assert "step.started" in event_types
            assert "step.completed" in event_types


class TestRunFetchFailure:
    """失败策略：超时重试 / 403不重试 / DNS失败 / SSRF拦截。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task = _make_task()
        self.step = _make_step()
        self.sse_bridge = MagicMock()
        self.db_session = AsyncMock()

    @pytest.mark.asyncio
    async def test_超时_重试1次_仍失败_SKIPPED(self):
        mock_sources = _make_mock_sources(1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        self.db_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.pipeline.fetcher._fetch_one_url") as mock_fetch:
            mock_fetch.return_value = _make_fetch_timeout_result()

            output = await run_fetch(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert output["successful"] == 0
            assert output["failed"] == 1

    @pytest.mark.asyncio
    async def test_HTTP403_不重试_直接SKIPPED(self):
        mock_sources = _make_mock_sources(1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        self.db_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.pipeline.fetcher._fetch_one_url") as mock_fetch:
            mock_fetch.return_value = _make_fetch_blocked_result(403)

            output = await run_fetch(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert output["successful"] == 0
            assert output["failed"] == 1

    @pytest.mark.asyncio
    async def test_SSRF拦截_内网URL_跳过(self):
        # 创建一个内网 URL 的 source
        src = MagicMock(spec=ResearchSource)
        src.id = 999
        src.url = "http://127.0.0.1:8080/admin"
        src.fetch_status = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [src]
        self.db_session.execute = AsyncMock(return_value=mock_result)

        output = await run_fetch(
            self.task, self.step, self.db_session, self.sse_bridge,
        )

        assert output["failed"] == 0
        assert output["skipped_safety"] == 1  # 安全拦截计数

    @pytest.mark.asyncio
    async def test_正文为空_SKIPPED(self):
        mock_sources = _make_mock_sources(1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        self.db_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.pipeline.fetcher._fetch_one_url") as mock_fetch:
            mock_fetch.return_value = {
                "status": "empty",
                "content": None,
                "content_length": None,
                "error": "正文提取为空",
            }

            output = await run_fetch(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert output["successful"] == 0
            assert output["failed"] == 1

    @pytest.mark.asyncio
    async def test_DNS失败_SKIPPED(self):
        mock_sources = _make_mock_sources(1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_sources
        self.db_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.pipeline.fetcher._fetch_one_url") as mock_fetch:
            mock_fetch.return_value = {
                "status": "dns_error",
                "content": None,
                "content_length": None,
                "error": "DNS解析失败",
            }

            output = await run_fetch(
                self.task, self.step, self.db_session, self.sse_bridge,
            )

            assert output["successful"] == 0
            assert output["failed"] == 1
