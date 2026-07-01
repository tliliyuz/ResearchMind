"""LLM 客户端单元测试 — 覆盖 app/core/llm.py 的流式/非流式调用与重试策略。

对齐 TESTING_STRATEGY.md §4.5：
- Mock AsyncOpenAI，保留 _classify_llm_error / _retry_delay / _max_retries 真实逻辑
- 验证各错误类型的重试次数和退避策略
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    LLMAuthFailedException,
    LLMRateLimitException,
    LLMTimeoutException,
    LLMUnknownException,
)
from app.core.llm import (
    LLMChunk,
    LLMResult,
    _classify_llm_error,
    _max_retries,
    _retry_delay,
    chat_completion,
    stream_chat_completion,
)


# ═══════════════════════════════════════════════════════════════
# 纯函数测试（不需要 Mock）
# ═══════════════════════════════════════════════════════════════


class TestClassifyLLMError:
    """错误分类"""

    def test_timeout关键词_返回LLMTimeoutException(self):
        assert _classify_llm_error("Request timed out") == LLMTimeoutException
        assert _classify_llm_error("operation timed out after 30s") == LLMTimeoutException

    def test_rate_limit或429_返回LLMRateLimitException(self):
        assert _classify_llm_error("rate_limit exceeded") == LLMRateLimitException
        assert _classify_llm_error("error 429 too many requests") == LLMRateLimitException

    def test_auth或401或403_返回LLMAuthFailedException(self):
        assert _classify_llm_error("auth failed") == LLMAuthFailedException
        assert _classify_llm_error("error 401 unauthorized") == LLMAuthFailedException
        assert _classify_llm_error("error 403 forbidden") == LLMAuthFailedException

    def test_其他错误_返回LLMUnknownException(self):
        assert _classify_llm_error("some unexpected error") == LLMUnknownException


class TestRetryDelay:
    """重试延迟计算"""

    def test_rate_limit_指数退避(self):
        assert _retry_delay(1, LLMRateLimitException) == 5.0   # 5 * 2^0
        assert _retry_delay(2, LLMRateLimitException) == 10.0  # 5 * 2^1

    def test_timeout_固定翻倍(self):
        assert _retry_delay(1, LLMTimeoutException) == 2.0
        assert _retry_delay(2, LLMTimeoutException) == 4.0

    def test_其他异常_固定2秒(self):
        assert _retry_delay(1, LLMUnknownException) == 2.0
        assert _retry_delay(2, LLMUnknownException) == 2.0


class TestMaxRetries:
    """最大重试次数"""

    def test_auth_error为0次(self):
        assert _max_retries(LLMAuthFailedException) == 0

    def test_unknown为1次(self):
        assert _max_retries(LLMUnknownException) == 1

    def test_timeout_rate_limit为3次(self):
        assert _max_retries(LLMTimeoutException) == 3
        assert _max_retries(LLMRateLimitException) == 3


# ═══════════════════════════════════════════════════════════════
# 共享 Mock 夹具
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def mock_llm_client():
    """Mock AsyncOpenAI 客户端 — 供流式/非流式测试类共用，避免重复定义。"""
    with patch("app.core.llm._get_llm_client") as mock_get:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock()
        mock_get.return_value = mock_client
        yield mock_client


# ═══════════════════════════════════════════════════════════════
# 流式调用测试
# ═══════════════════════════════════════════════════════════════


class TestStreamChatCompletion:
    """stream_chat_completion — 流式 LLM 调用"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_llm_client):
        self.mock_client = mock_llm_client

    def _make_stream_chunks(self, contents):
        """生成模拟的流式 chunk 列表"""
        async def mock_stream():
            for content in contents:
                choice = MagicMock()
                choice.delta = MagicMock()
                choice.delta.content = content
                choice.delta.reasoning_content = ""
                choice.finish_reason = None
                chunk = MagicMock()
                chunk.choices = [choice]
                yield chunk
            # 最后发送 finish chunk
            choice = MagicMock()
            choice.delta = MagicMock()
            choice.delta.content = ""
            choice.finish_reason = "stop"
            chunk = MagicMock()
            chunk.choices = [choice]
            yield chunk
        return mock_stream()

    async def test_正常流式调用_逐chunk返回content(self):
        messages = [{"role": "user", "content": "Hello"}]
        self.mock_client.chat.completions.create.return_value = self._make_stream_chunks(
            ["Hello", " world", "!"]
        )

        chunks = []
        async for chunk in stream_chat_completion(messages):
            chunks.append(chunk)

        total_content = "".join(c.content for c in chunks)
        assert total_content == "Hello world!"
        # 最后一个 chunk 有 finish_reason
        assert chunks[-1].finish_reason == "stop"

    async def test_timeout错误_重试3次后抛出LLMTimeoutException(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.side_effect = Exception(
            "Request timed out after 30 seconds"
        )

        with pytest.raises(LLMTimeoutException):
            async for _ in stream_chat_completion(messages):
                pass

        # 1 次初始调用 + 3 次重试 = 4 次（_max_retries(timeout)=3，即重试 3 次）
        # 但实际上循环中 attempt from 1..3，首次 attempt=1（初始调用），
        # 若 attempt > max_retry（即 >3）才停止，所以会尝试 3 次。
        # 重读代码: for attempt in range(1, 4): → attempt=1,2,3
        # attempt=3 时 max_retry=3, 3>3 is False → 还会重试
        # 所以总共 3 次调用（初始+2次重试）
        assert self.mock_client.chat.completions.create.call_count == 3

    async def test_auth错误_0次重试_直接抛出LLMAuthFailedException(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.side_effect = Exception(
            "Error 401 Unauthorized - invalid API key"
        )

        with pytest.raises(LLMAuthFailedException):
            async for _ in stream_chat_completion(messages):
                pass

        # auth 错误 max_retries=0 → attempt=1(>0) → 直接抛异常
        assert self.mock_client.chat.completions.create.call_count == 1

    async def test_rate_limit错误_指数退避重试3次(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.side_effect = Exception(
            "Error 429 rate_limit_exceeded"
        )

        # Mock asyncio.sleep 加速测试
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMRateLimitException):
                async for _ in stream_chat_completion(messages):
                    pass

            # rate_limit max_retries=3，循环 attempt=1,2,3 共 3 次调用
            assert self.mock_client.chat.completions.create.call_count == 3
            # 指数退避 5.0 / 10.0 / 20.0（每次失败后均 sleep，最后一次 sleep 后循环结束抛出）
            assert mock_sleep.call_count == 3
            assert mock_sleep.call_args_list[0][0][0] == 5.0
            assert mock_sleep.call_args_list[1][0][0] == 10.0
            assert mock_sleep.call_args_list[2][0][0] == 20.0


# ═══════════════════════════════════════════════════════════════
# 非流式调用测试
# ═══════════════════════════════════════════════════════════════


class TestChatCompletion:
    """chat_completion — 非流式 LLM 调用"""

    @pytest.fixture(autouse=True)
    def _setup(self, mock_llm_client):
        self.mock_client = mock_llm_client

    def _make_response(self, content="response", prompt_tokens=10, completion_tokens=5, total_tokens=15):
        choice = MagicMock()
        choice.message = MagicMock()
        choice.message.content = content
        choice.message.reasoning_content = ""
        usage = MagicMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        usage.total_tokens = total_tokens
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        return response

    async def test_正常调用_返回LLMResult含token统计(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.return_value = self._make_response(
            content="The answer", prompt_tokens=50, completion_tokens=20, total_tokens=70,
        )

        result = await chat_completion(messages)

        assert isinstance(result, LLMResult)
        assert result.content == "The answer"
        assert result.prompt_tokens == 50
        assert result.completion_tokens == 20
        assert result.total_tokens == 70
        assert result.duration_ms >= 0
        assert result.model == "mimo-v2.5"

    async def test_显式指定model_返回结果携带该模型名(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.return_value = self._make_response()

        result = await chat_completion(messages, model="deepseek-v4-pro")

        assert result.model == "deepseek-v4-pro"
        assert result.duration_ms >= 0

    async def test_timeout错误_重试3次后抛异常(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.side_effect = Exception(
            "Operation timed out"
        )

        with pytest.raises(LLMTimeoutException):
            await chat_completion(messages)

        assert self.mock_client.chat.completions.create.call_count == 3

    async def test_auth错误_0次重试(self):
        messages = [{"role": "user", "content": "Test"}]
        self.mock_client.chat.completions.create.side_effect = Exception(
            "Authentication failed"
        )

        with pytest.raises(LLMAuthFailedException):
            await chat_completion(messages)

        assert self.mock_client.chat.completions.create.call_count == 1

    async def test_空choices抛出LLMUnknownException(self):
        """LLM 返回空 choices → 抛出 LLMUnknownException（E3111，不重试）"""
        messages = [{"role": "user", "content": "Test"}]
        response = MagicMock()
        response.choices = []  # 空
        self.mock_client.chat.completions.create.return_value = response

        with pytest.raises(LLMUnknownException) as exc_info:
            await chat_completion(messages)
        assert exc_info.value.error_code == "E3111"
        # 空结果不重试，仅调用 1 次
        assert self.mock_client.chat.completions.create.call_count == 1

    async def test_dict形式tool_choice透传(self):
        """chat_completion 接受 dict 形式 tool_choice 并透传至请求参数"""
        messages = [{"role": "user", "content": "Test"}]
        tools = [{"type": "function", "function": {"name": "plan_tool"}}]
        tool_choice = {"type": "function", "function": {"name": "plan_tool"}}
        self.mock_client.chat.completions.create.return_value = self._make_response()

        await chat_completion(messages, tools=tools, tool_choice=tool_choice)

        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tools"] == tools
        assert call_kwargs["tool_choice"] == tool_choice

    async def test_stream支持tools和tool_choice透传(self):
        """stream_chat_completion 支持 tools/tool_choice 并透传"""
        from app.core.llm import stream_chat_completion

        messages = [{"role": "user", "content": "Test"}]
        tools = [{"type": "function", "function": {"name": "plan_tool"}}]
        tool_choice = "auto"

        async def mock_stream():
            choice = MagicMock()
            choice.delta = MagicMock()
            choice.delta.content = ""
            choice.delta.reasoning_content = ""
            choice.delta.tool_calls = []
            choice.finish_reason = "stop"
            chunk = MagicMock()
            chunk.choices = [choice]
            yield chunk

        self.mock_client.chat.completions.create.return_value = mock_stream()

        chunks = []
        async for chunk in stream_chat_completion(messages, tools=tools, tool_choice=tool_choice):
            chunks.append(chunk)

        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["tools"] == tools
        assert call_kwargs["tool_choice"] == tool_choice
        assert chunks[-1].finish_reason == "stop"
