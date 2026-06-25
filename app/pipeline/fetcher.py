"""Fetch 阶段 —— 网页内容抓取 + trafilatura 正文提取 + 安全校验。

对齐 RESEARCH_PIPELINE.md §4：
- URL 安全检查（协议白名单 + IP 黑名单 SSRF 防护）
- HTTP GET + trafilatura 正文提取 + 内容截断
- 子 step 管理（每个 URL 独立 ResearchStep）
- 写入 research_sources 表
- 失败策略：超时重试 1 次 / 403/404/DNS → 直接 SKIPPED
"""

import asyncio
import ipaddress
import logging
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

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

logger = logging.getLogger(__name__)

# ── 安全常量 ──────────────────────────────────────────────────

_ALLOWED_PROTOCOLS = {"http", "https"}

# 内网 IP 范围（CIDR 表示法）
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # 回环
    ipaddress.ip_network("10.0.0.0/8"),         # A 类私有
    ipaddress.ip_network("172.16.0.0/12"),      # B 类私有
    ipaddress.ip_network("192.168.0.0/16"),     # C 类私有
    ipaddress.ip_network("169.254.0.0/16"),     # 链路本地
    ipaddress.ip_network("0.0.0.0/8"),           # 当前网络
    ipaddress.ip_network("::1/128"),             # IPv6 回环
    ipaddress.ip_network("fc00::/7"),            # IPv6 唯一本地
    ipaddress.ip_network("fe80::/10"),           # IPv6 链路本地
]

_USER_AGENT = "ResearchMind/1.0 (research-agent; +https://github.com/ResearchMind)"
_MAX_RESPONSE_BODY = 2 * 1024 * 1024  # 2MB，超过则跳过（config.py 未设此项，Phase4 评估后添加）


async def _check_url_safety(url: str) -> str | None:
    """URL 安全检查。返回 None = 通过，返回字符串 = 拒绝原因。

    检查项（对齐 RESEARCH_PIPELINE.md §4.4）：
    1. 协议白名单：仅 http/https
    2. IP 黑名单：禁止内网 IP（SSRF 防护）
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "URL 解析失败"

    # 协议检查
    if parsed.scheme.lower() not in _ALLOWED_PROTOCOLS:
        return f"协议 {parsed.scheme} 不在白名单中（仅 http/https）"

    hostname = parsed.hostname
    if not hostname:
        return "URL 缺少 hostname"

    # IP 黑名单检查（SSRF 防护）
    # DNS 解析通过 run_in_executor 异步化，避免阻塞 Worker 协程
    try:
        loop = asyncio.get_running_loop()
        ip_addr = await loop.run_in_executor(None, socket.gethostbyname, hostname)
        ip_obj = ipaddress.ip_address(ip_addr)
        for network in _PRIVATE_NETWORKS:
            if ip_obj in network:
                return f"IP {ip_addr} 属于内网地址 {network}，拒绝访问（SSRF 防护）"
    except (socket.gaierror, ValueError):
        # DNS 解析失败 → 在 _fetch_one_url 中作为 fetch 失败处理，不在安全层拦截
        pass

    return None


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
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = await client.get(url)

            # HTTP 状态码检查
            if response.status_code == 403:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"HTTP 403 Forbidden"}
            if response.status_code == 404:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"HTTP 404 Not Found"}
            if response.status_code >= 500:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"HTTP {response.status_code} Server Error"}
            if response.status_code != 200:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"HTTP {response.status_code}"}

            # 检查响应体大小
            content_length_header = response.headers.get("content-length")
            if content_length_header and int(content_length_header) > _MAX_RESPONSE_BODY:
                return {"status": "blocked", "content": None, "content_length": None,
                        "error": f"响应体过大: {content_length_header} bytes"}

            html_content = response.text

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

    logger.info("Fetch 开始: task_id=%s, urls=%d", task_id, len(sources))

    fetched_results: list[dict] = []
    successful = 0
    failed = 0
    skipped_safety = 0

    for source in sources:
        url = source.url
        source_id = source.id

        # 创建子 step
        child_step = await _create_fetch_child_step(
            session, task, step, label=f"抓取: {url[:100]}",
        )
        child_step_id = str(child_step.id)

        # 发射子 step.started
        sse_bridge.publish(EVENT_STEP_STARTED, {
            "step_id": child_step_id,
            "step_type": "fetch",
            "label": child_step.label,
            "url": url,
            "parent_step_id": root_step_id,
        })

        # a. 安全检查
        safety_error = await _check_url_safety(url)
        if safety_error:
            logger.warning("Fetch URL 安全拦截: url=%s, reason=%s", url, safety_error)
            source.fetch_status = "blocked"
            await _finish_fetch_child_step(session, child_step, "skipped")
            sse_bridge.publish(EVENT_STEP_SKIPPED, {
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
            sse_bridge.publish(EVENT_STEP_COMPLETED, {
                "step_id": child_step_id,
                "url": url,
                "content_length": fetch_result["content_length"],
            })
        else:
            failed += 1
            await _finish_fetch_child_step(session, child_step, "skipped")
            sse_bridge.publish(EVENT_STEP_SKIPPED, {
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
    task.total_steps = (task.total_steps or 0) + 1
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
