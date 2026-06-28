"""Fetch 阶段 —— 网页内容抓取 + trafilatura 正文提取 + 安全校验。

对齐 RESEARCH_PIPELINE.md §4：
- URL 安全检查（协议白名单 + IP 黑名单 SSRF 防护）
- HTTP GET + trafilatura 正文提取 + 内容截断
- 子 step 管理（每个 URL 独立 ResearchStep）
- 写入 research_sources 表
- 失败策略：超时重试 1 次 / 403/404/DNS → 直接 SKIPPED
"""

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.research_source import ResearchSource
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_SKIPPED,
    EVENT_STEP_STARTED,
)
from app.utils.url_safety import check_url_safety

logger = logging.getLogger(__name__)

_USER_AGENT = "ResearchMind/1.0 (research-agent; +https://github.com/ResearchMind)"


async def _fetch_one_url(
    url: str,
    retry_on_timeout: bool = True,
) -> dict:
    """抓取单个 URL，返回结果 dict。

    Args:
        url: 目标 URL
        retry_on_timeout: 超时场景是否重试（首次调用为 True）

    Returns:
        {
            "status": "success" | "timeout" | "blocked" | "empty" | "dns_error",
            "content": str | None,       # 截断后的 Markdown 正文（仅 success）
            "content_length": int | None, # 原始正文长度（仅 success）
            "error": str | None,          # 错误描述（非 success）
        }
    """
    # 初始 URL 安全检查
    safety_error = await check_url_safety(url)
    if safety_error:
        return {"status": "blocked", "content": None, "content_length": None,
                "error": f"安全拦截: {safety_error}"}

    timeout_config = httpx.Timeout(
        connect=10.0,
        read=settings.FETCH_TIMEOUT,
        write=10.0,
        pool=5.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout_config,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            follow_redirects=False,
        ) as client:
            current_url = url
            redirect_count = 0
            max_redirects = 5

            while True:
                response = await client.get(current_url)

                # 处理重定向
                if 300 <= response.status_code < 400:
                    redirect_count += 1
                    if redirect_count > max_redirects:
                        return {"status": "blocked", "content": None, "content_length": None,
                                "error": "重定向次数超过上限"}

                    location = response.headers.get("location")
                    if not location:
                        return {"status": "blocked", "content": None, "content_length": None,
                                "error": "重定向响应缺少 Location 头"}

                    current_url = urljoin(str(response.url), location)
                    safety_error = await check_url_safety(current_url)
                    if safety_error:
                        return {"status": "blocked", "content": None, "content_length": None,
                                "error": f"重定向后安全拦截: {safety_error}"}
                    continue

                break

            # HTTP 状态码检查
            if response.status_code == 403:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": "HTTP 403 Forbidden"}
            if response.status_code == 404:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": "HTTP 404 Not Found"}
            if response.status_code >= 500:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"HTTP {response.status_code} Server Error"}
            if response.status_code != 200:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"HTTP {response.status_code}"}

            # 检查响应体大小（Content-Length 头作为早期拦截）
            content_length_header = response.headers.get("content-length")
            if content_length_header and int(content_length_header) > settings.FETCH_MAX_BODY_SIZE:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"响应体过大: {content_length_header} bytes"}

            # 流式读取并限制最大字节数，防止 Content-Length 缺失时内存耗尽
            content_bytes = b""
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                content_bytes += chunk
                if len(content_bytes) > settings.FETCH_MAX_BODY_SIZE:
                    return {"status": "blocked", "content": None, "content_length": None,
                            "error": f"响应体超过 {settings.FETCH_MAX_BODY_SIZE} bytes 上限"}

            try:
                html_content = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                html_content = content_bytes.decode("latin-1", errors="replace")

    except httpx.TimeoutException:
        if retry_on_timeout:
            logger.info("Fetch 超时，重试 1 次: url=%s", url)
            return await _fetch_one_url(url, retry_on_timeout=False)
        return {"status": "timeout", "content": None, "content_length": None,
                "error": "请求超时（重试后仍失败）"}
    except (httpx.ConnectError, socket.gaierror) as e:
        return {"status": "dns_error", "content": None, "content_length": None,
                "error": f"DNS 解析/连接失败: {e}"}
    except Exception as e:
        return {"status": "blocked", "content": None, "content_length": None,
                "error": f"请求异常: {e}"}

    # 正文提取（trafilatura）
    if not html_content or not html_content.strip():
        return {"status": "empty", "content": None, "content_length": None,
                "error": "响应体为空"}

    try:
        import trafilatura
        extracted = trafilatura.extract(
            html_content,
            output_format="markdown",
            with_metadata=True,
            favor_precision=True,
        )
    except Exception as e:
        logger.warning("trafilatura 提取异常: url=%s, error=%s", url, e)
        return {"status": "empty", "content": None, "content_length": None,
                "error": f"正文提取异常: {e}"}

    if not extracted or not extracted.strip():
        return {"status": "empty", "content": None, "content_length": None,
                "error": "正文提取为空"}

    original_length = len(extracted)

    # 内容截断（100KB）
    if original_length > settings.FETCH_MAX_CONTENT_LENGTH:
        # 按字符边界截断（避免截断多字节 UTF-8 字符）
        truncated = extracted[:settings.FETCH_MAX_CONTENT_LENGTH]
        # 回退到最后一个完整段落
        last_para = truncated.rfind("\n\n")
        if last_para > settings.FETCH_MAX_CONTENT_LENGTH // 2:
            truncated = truncated[:last_para]
        content = truncated
    else:
        content = extracted

    return {
        "status": "success",
        "content": content,
        "content_length": original_length,
        "error": None,
    }


async def run_fetch(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge: SSEBridge,
) -> dict:
    """执行 Fetch 阶段。

    1. 读取 Search 阶段创建的 ResearchSource 行（fetch_status IS NULL）
    2. 对每个 URL：
       a. 安全检查
       b. HTTP GET + trafilatura 提取
       c. 更新 ResearchSource 行
       d. 创建子 ResearchStep
    3. 失败策略（超时重试 1 次 / 403/404/DNS → SKIPPED）
    4. 更新 task.total_sources 统计

    Returns:
        output dict
    """
    task_id = str(task.id)
    root_step_id = str(step.id)

    # 1. 读取待抓取的 URL 列表
    stmt = (
        select(ResearchSource)
        .where(
            ResearchSource.task_id == task.id,
            ResearchSource.fetch_status.is_(None),
        )
    )
    result = await session.execute(stmt)
    sources: list[ResearchSource] = list(result.scalars().all())

    if not sources:
        logger.info("Fetch: 无待抓取 URL，跳过: task_id=%s", task_id)
        return {
            "fetched": [],
            "successful": 0,
            "failed": 0,
            "skipped_safety": 0,
            "message": "无待抓取 URL",
        }

    # 每任务 URL 硬上限：超出部分不处理
    original_source_count = len(sources)
    if original_source_count > settings.FETCH_MAX_URLS_PER_TASK:
        logger.warning(
            "Fetch URL 数量超过每任务硬限制 %d，截断处理: task_id=%s",
            settings.FETCH_MAX_URLS_PER_TASK, task_id,
        )
        sources = sources[:settings.FETCH_MAX_URLS_PER_TASK]

    logger.info("Fetch 开始: task_id=%s, urls=%d", task_id, len(sources))

    fetched_results: list[dict] = []
    successful = 0
    failed = 0
    skipped_safety = 0
    truncated_count = original_source_count - len(sources)

    for source in sources:
        url = source.url
        source_id = source.id

        # 创建子 step
        child_step = await _create_fetch_child_step(
            session, task, step, label=f"抓取: {url[:100]}",
        )
        child_step_id = str(child_step.id)

        # 发射子 step.started
        await sse_bridge.publish(EVENT_STEP_STARTED, {
            "step_id": child_step_id,
            "step_type": "fetch",
            "label": child_step.label,
            "url": url,
            "parent_step_id": root_step_id,
        })

        # a. 安全检查
        safety_error = await check_url_safety(url)
        if safety_error:
            logger.warning("Fetch URL 安全拦截: url=%s, reason=%s", url, safety_error)
            source.fetch_status = "blocked"
            await _finish_fetch_child_step(session, child_step, "skipped")
            await sse_bridge.publish(EVENT_STEP_SKIPPED, {
                "step_id": child_step_id,
                "url": url,
                "reason": safety_error,
            })
            skipped_safety += 1
            fetched_results.append({"url": url, "status": "blocked", "error": safety_error})
            await session.flush()
            continue

        # b-c. HTTP GET + 正文提取
        fetch_result = await _fetch_one_url(url)

        # d. 更新 ResearchSource
        source.fetched_at = datetime.now(timezone.utc)
        source.fetch_status = fetch_result["status"]

        if fetch_result["status"] == "success":
            source.title = _extract_title_from_content(
                fetch_result.get("content", ""), url,
            )[:500]
            source.domain = _extract_domain(url)[:255]
            source.content = fetch_result["content"]
            successful += 1

            # 子 step → completed
            child_output = {
                "url": url,
                "status": "success",
                "content_length": fetch_result["content_length"],
            }
            await _finish_fetch_child_step(session, child_step, "completed", child_output)
            await sse_bridge.publish(EVENT_STEP_COMPLETED, {
                "step_id": child_step_id,
                "url": url,
                "content_length": fetch_result["content_length"],
            })
        else:
            failed += 1
            await _finish_fetch_child_step(session, child_step, "skipped")
            await sse_bridge.publish(EVENT_STEP_SKIPPED, {
                "step_id": child_step_id,
                "url": url,
                "reason": fetch_result.get("error", "未知错误"),
            })

        fetched_results.append({
            "url": url,
            "source_id": source_id,
            "step_id": child_step_id,
            "status": fetch_result["status"],
            "content_length": fetch_result.get("content_length"),
            "error": fetch_result.get("error"),
        })

        await session.flush()

    # 更新 task 统计
    task.total_sources = successful
    await session.flush()

    output = {
        "fetched": fetched_results,
        "successful": successful,
        "failed": failed,
        "skipped_safety": skipped_safety,
        "truncated": truncated_count,
    }

    logger.info(
        "Fetch 完成: task_id=%s, success=%d, failed=%d, safety_skip=%d",
        task_id, successful, failed, skipped_safety,
    )
    return output


# ── 辅助函数 ──────────────────────────────────────────────────


def _extract_domain(url: str) -> str:
    """从 URL 提取域名。"""
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _extract_title_from_content(content: str | None, fallback_url: str) -> str:
    """从 Markdown 内容中提取第一个 # 标题作为页面标题。"""
    if not content:
        return _extract_domain(fallback_url)
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and len(stripped) > 2:
            return stripped[2:].strip()[:500]
    # 无标题 → 使用域名
    return _extract_domain(fallback_url)


async def _create_fetch_child_step(
    session: AsyncSession,
    task: ResearchTask,
    parent_step: ResearchStep,
    label: str,
) -> ResearchStep:
    """创建 Fetch 子 ResearchStep。"""
    now = datetime.now(timezone.utc)
    child = ResearchStep(
        task_id=task.id,
        step_type="fetch",
        parent_step_id=parent_step.id,
        status="running",
        label=label,
        started_at=now,
    )
    session.add(child)
    await session.flush()
    return child


async def _finish_fetch_child_step(
    session: AsyncSession,
    child_step: ResearchStep,
    status: str,
    output: dict | None = None,
) -> None:
    """完成 Fetch 子 step。"""
    now = datetime.now(timezone.utc)
    child_step.status = status
    child_step.completed_at = now
    if child_step.started_at:
        delta = now - child_step.started_at
        child_step.duration_ms = int(delta.total_seconds() * 1000)
    if output is not None:
        child_step.output = output
    await session.flush()
