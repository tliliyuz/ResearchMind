"""LLM 调用模块 — DeepSeek API（OpenAI 兼容），流式 chat/completions

对齐 ARCHITECTURE.md §1 技术选型：
- DeepSeek API (OpenAI 兼容接口) 作为 LLM 后端
- 流式 chat/completions 用于需要流式输出的场景（Render）
- 非流式 chat/completions 用于需要全量结果的场景（Planning / Synthesis）

[Deviation] ResearchMind LLM 增强：
- 新增重试逻辑：timeout（3次）/ rate_limit（3次指数退避）/ auth_error（不重试）
- 非流式调用默认模型改为 LLM_FLASH_MODEL（deepseek-v4-flash），区别于流式的 LLM_MODEL（deepseek-v4-pro）
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings
from app.core.exceptions import (
    LLMAuthFailedException,
    LLMRateLimitException,
    LLMTimeoutException,
    LLMUnknownException,
)

logger = logging.getLogger(__name__)

# 模块级单例：AsyncOpenAI 客户端（避免每次请求新建实例）
_llm_client: AsyncOpenAI | None = None


@dataclass
class LLMChunk:
    """LLM 流式输出的单个 chunk"""
    content: str = ""
    reasoning_content: str = ""
    finish_reason: str | None = None


@dataclass
class LLMResult:
    """LLM 非流式调用结果"""
    content: str
    reasoning_content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def _get_llm_client() -> AsyncOpenAI:
    """获取 AsyncOpenAI 客户端实例（模块级惰性单例）。"""
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
        )
    return _llm_client


# ── 错误分类 ────────────────────────────────────────────


def _classify_llm_error(error_msg: str) -> type:
    """根据错误信息分类 LLM 异常类型。

    用于重试策略决策：
    - timeout → 可重试（LLMTimeoutException）
    - rate_limit / 429 → 可重试（LLMRateLimitException）
    - auth / 401 → 不可重试（LLMAuthFailedException）
    - 其他 → 可重试一次（LLMUnknownException）
    """
    msg_lower = error_msg.lower()
    if "timeout" in msg_lower or "timed out" in msg_lower:
        return LLMTimeoutException
    if "rate_limit" in msg_lower or "429" in msg_lower or "too many requests" in msg_lower:
        return LLMRateLimitException
    if "auth" in msg_lower or "401" in msg_lower or "403" in msg_lower or "unauthorized" in msg_lower:
        return LLMAuthFailedException
    return LLMUnknownException


# ── 重试策略 ────────────────────────────────────────────


def _retry_delay(attempt: int, exc_type: type) -> float:
    """计算重试延迟（秒）。

    - timeout：固定 2s/4s/8s
    - rate_limit：指数退避 5s/10s/20s
    - 其他：固定 2s
    """
    if exc_type is LLMRateLimitException:
        return 5.0 * (2 ** (attempt - 1))
    if exc_type is LLMTimeoutException:
        return 2.0 * (2 ** (attempt - 1))
    return 2.0


def _max_retries(exc_type: type) -> int:
    """返回每种异常类型的最大重试次数。

    - timeout：3 次
    - rate_limit：3 次（指数退避）
    - auth_error：0 次（不重试）
    - unknown：1 次
    """
    if exc_type is LLMAuthFailedException:
        return 0
    if exc_type is LLMUnknownException:
        return 1
    return 3


# ── 流式调用 ─────────────────────────────────────────────


async def stream_chat_completion(
    messages: list[dict[str, str]],
    deep_thinking: bool = False,
    reasoning_effort: str = "high",
    model: str | None = None,
    temperature: float | None = None,
) -> AsyncIterator[LLMChunk]:
    """流式调用 LLM chat/completions。

    Args:
        messages: OpenAI 格式的消息列表
        deep_thinking: 是否启用深度思考（DeepSeek thinking 参数）
        reasoning_effort: 推理强度（仅 deep_thinking=true 时传递）
        model: 模型名称（None 时使用 settings.LLM_MODEL）

    Yields:
        LLMChunk: 流式输出的 content 和 reasoning_content

    Raises:
        LLMUnknownException: 调用返回未预期错误（重试耗尽后）
    """
    client = _get_llm_client()
    llm_model = model or settings.LLM_MODEL

    # 构建请求参数
    thinking_type = "enabled" if deep_thinking else "disabled"
    extra_body = {"thinking": {"type": thinking_type}}
    request_kwargs = {
        "model": llm_model,
        "messages": messages,
        "stream": True,
        "extra_body": extra_body,
    }
    if deep_thinking:
        request_kwargs["reasoning_effort"] = reasoning_effort
    if temperature is not None:
        request_kwargs["temperature"] = temperature

    last_exc_type = LLMUnknownException
    for attempt in range(1, 4):  # 最多 3 次尝试（含首次）
        try:
            logger.info(f"调用 LLM (流式): model={llm_model}, deep_thinking={deep_thinking}")
            t0 = time.perf_counter()
            t_first = None

            stream = await client.chat.completions.create(**request_kwargs)

            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                content = delta.content or ""
                reasoning_content = getattr(delta, "reasoning_content", "") or ""

                if t_first is None and (content or reasoning_content):
                    t_first = time.perf_counter()
                    logger.info("LLM_PERF(流式) 首Token=%.3fs", t_first - t0)

                yield LLMChunk(
                    content=content,
                    reasoning_content=reasoning_content,
                    finish_reason=choice.finish_reason,
                )
            return  # 成功，退出重试循环

        except Exception as e:
            error_msg = str(e)
            exc_type = _classify_llm_error(error_msg)
            max_retry = _max_retries(exc_type)
            last_exc_type = exc_type

            if attempt > max_retry:
                logger.error(f"LLM 流式调用失败（重试耗尽）: {error_msg}")
                raise exc_type(detail=error_msg)

            delay = _retry_delay(attempt, exc_type)
            logger.warning(
                f"LLM 流式调用失败（{exc_type.__name__}），"
                f"第 {attempt}/{max_retry} 次重试，等待 {delay}s: {error_msg}"
            )
            await asyncio.sleep(delay)

    # 不应到达此处
    raise last_exc_type(detail="LLM 流式调用重试耗尽")


# ── 非流式调用 ───────────────────────────────────────────


async def chat_completion(
    messages: list[dict[str, str]],
    deep_thinking: bool = False,
    reasoning_effort: str = "high",
    max_tokens: int | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> LLMResult:
    """非流式调用 LLM chat/completions（用于 Planning / Synthesis / Rerank 等场景）。

    Args:
        messages: OpenAI 格式的消息列表
        deep_thinking: 是否启用深度思考
        reasoning_effort: 推理强度
        max_tokens: 最大输出 token 数（None 时使用模型默认值）
        model: 模型名称（None 时使用 settings.LLM_FLASH_MODEL，适合轻量任务）

    Returns:
        LLMResult: 包含 content、reasoning_content、token 使用量

    Raises:
        LLMUnknownException: 调用返回未预期错误（重试耗尽后）
    """
    client = _get_llm_client()
    llm_model = model or settings.LLM_FLASH_MODEL

    thinking_type = "enabled" if deep_thinking else "disabled"
    extra_body = {"thinking": {"type": thinking_type}}
    request_kwargs = {
        "model": llm_model,
        "messages": messages,
        "stream": False,
        "extra_body": extra_body,
    }
    if deep_thinking:
        request_kwargs["reasoning_effort"] = reasoning_effort
    if max_tokens is not None:
        request_kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        request_kwargs["temperature"] = temperature

    last_exc_type = LLMUnknownException
    for attempt in range(1, 4):
        try:
            logger.info(f"调用 LLM (非流式): model={llm_model}")
            t0 = time.perf_counter()

            response = await client.chat.completions.create(**request_kwargs)
            t_api = time.perf_counter()

            if not response.choices:
                raise LLMUnknownException(detail="LLM 返回空结果")

            choice = response.choices[0]
            content = choice.message.content or ""
            reasoning_content = getattr(choice.message, "reasoning_content", "") or ""

            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            logger.info(
                "LLM_PERF(非流式) api=%.3fs prompt_tok=%d completion_tok=%d",
                t_api - t0, prompt_tokens, completion_tokens,
            )

            return LLMResult(
                content=content,
                reasoning_content=reasoning_content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

        except (LLMUnknownException, LLMAuthFailedException):
            # 空结果 / 认证失败不重试，直接抛出
            raise
        except Exception as e:
            error_msg = str(e)
            exc_type = _classify_llm_error(error_msg)
            max_retry = _max_retries(exc_type)
            last_exc_type = exc_type

            if attempt > max_retry:
                logger.error(f"LLM 非流式调用失败（重试耗尽）: {error_msg}")
                raise exc_type(detail=error_msg)

            delay = _retry_delay(attempt, exc_type)
            logger.warning(
                f"LLM 非流式调用失败（{exc_type.__name__}），"
                f"第 {attempt}/{max_retry} 次重试，等待 {delay}s: {error_msg}"
            )
            await asyncio.sleep(delay)

    raise last_exc_type(detail="LLM 非流式调用重试耗尽")
