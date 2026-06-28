"""Search 阶段 —— Tavily API 多子问题搜索 + URL 去重。

对齐 RESEARCH_PIPELINE.md §3：
- 对 Planning 产出的每个 SubQuestion 调用 Tavily Search API
- 跨子问题 URL 去重（保留首次出现的归属）
- 子 step 管理（每个子问题独立 ResearchStep）
- 失败策略：单子问题可降级 SKIPPED / 全部失败 → E3102
"""

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import SearchFailedException
from app.models.research_step import ResearchStep
from app.models.research_source import ResearchSource
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_PROGRESS,
    EVENT_STEP_SKIPPED,
    EVENT_STEP_STARTED,
)

logger = logging.getLogger(__name__)

# 搜索重试策略（config.py 未设对应项，Phase4 评估后添加）
_SEARCH_RETRY_MAX = 2
_SEARCH_RETRY_DELAYS = [1.0, 2.0]  # 指数退避


async def _call_tavily(query: str, api_key: str) -> dict:
    """调用 Tavily Search API 单次查询。

    Args:
        query: 搜索查询字符串
        api_key: Tavily API key

    Returns:
        Tavily API 响应 JSON

    Raises:
        httpx.HTTPError: 网络/API 错误
    """
    url = f"{settings.TAVILY_BASE_URL}/search"

    payload = {
        "query": query,
        "search_depth": settings.TAVILY_SEARCH_DEPTH,
        "max_results": settings.TAVILY_MAX_RESULTS_PER_QUERY,
        "include_answer": False,
        "include_raw_content": False,
        "api_key": api_key,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def _search_one_sub_question(
    sub_question: str,
    index: int,
    api_key: str,
) -> list[dict]:
    """搜索单个子问题，含重试逻辑。

    Args:
        sub_question: 子问题文本
        index: 子问题序号（1-based，仅用于日志）
        api_key: Tavily API key

    Returns:
        Tavily 搜索结果列表（每条含 url/title/snippet/score）

    Raises:
        RuntimeError: 重试耗尽后仍失败
    """
    last_error: Exception | None = None

    for retry in range(_SEARCH_RETRY_MAX + 1):
        try:
            response = await _call_tavily(sub_question, api_key)
            results = response.get("results", [])
            logger.info(
                "Search 子问题 %d 完成: query=%r, results=%d",
                index, sub_question[:60], len(results),
            )
            return results

        except httpx.HTTPStatusError as e:
            last_error = e
            # 4xx 不重试（API key 错误等）
            if 400 <= e.response.status_code < 500:
                logger.warning(
                    "Search 子问题 %d 客户端错误 %d，不重试: %s",
                    index, e.response.status_code, e,
                )
                raise
            # 5xx 可重试
            if retry < _SEARCH_RETRY_MAX:
                delay = _SEARCH_RETRY_DELAYS[retry]
                logger.warning(
                    "Search 子问题 %d 服务端错误，第 %d/%d 次重试，等待 %.1fs: %s",
                    index, retry + 1, _SEARCH_RETRY_MAX, delay, e,
                )
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"Tavily API 服务端错误（重试 {_SEARCH_RETRY_MAX} 次耗尽）") from e

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
            if retry < _SEARCH_RETRY_MAX:
                delay = _SEARCH_RETRY_DELAYS[retry]
                logger.warning(
                    "Search 子问题 %d 超时/连接错误，第 %d/%d 次重试，等待 %.1fs: %s",
                    index, retry + 1, _SEARCH_RETRY_MAX, delay, e,
                )
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"Tavily API 网络错误（重试 {_SEARCH_RETRY_MAX} 次耗尽）") from e

        except Exception as e:
            last_error = e
            if retry < _SEARCH_RETRY_MAX:
                delay = _SEARCH_RETRY_DELAYS[retry]
                logger.warning(
                    "Search 子问题 %d 未知错误，第 %d/%d 次重试，等待 %.1fs: %s",
                    index, retry + 1, _SEARCH_RETRY_MAX, delay, e,
                )
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"Tavily API 未知错误（重试 {_SEARCH_RETRY_MAX} 次耗尽）") from e

    raise RuntimeError(f"Search 子问题 {index} 意外退出") from last_error


def _extract_domain(url: str) -> str:
    """从 URL 提取域名。"""
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


async def run_search(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge: SSEBridge,
) -> dict:
    """执行 Search 阶段。

    1. 读取 Planning 产出的 SubQuestion[]
    2. 对每个 SubQuestion 调用 Tavily Search API（含重试）
    3. 创建子 ResearchStep（每个子问题独立）
    4. 跨子问题 URL 去重
    5. 写入 ResearchSource 行
    6. 失败策略：单子问题可降级 SKIPPED / 全部失败 → E3102

    Returns:
        output dict
    """
    task_id = str(task.id)
    root_step_id = str(step.id)

    # 1. 读取 Planning 输出（显式查询，避免异步 relationship 懒加载）
    sub_questions = await _load_sub_questions(session, task)
    if not sub_questions:
        logger.warning("Search: 无子问题输入，跳过: task_id=%s", task_id)
        return {
            "total_results": 0,
            "after_dedup": 0,
            "sub_question_results": [],
            "sources_created": 0,
            "message": "无子问题输入",
        }

    logger.info("Search 开始: task_id=%s, sub_questions=%d", task_id, len(sub_questions))

    api_key = settings.TAVILY_API_KEY
    if not api_key:
        raise SearchFailedException(detail="TAVILY_API_KEY 未配置")

    # 2. 搜索每个子问题
    all_results: list[dict] = []  # 所有原始结果
    sub_results: list[dict] = []  # 每个子问题的汇总
    seen_urls: set[str] = set()
    all_skipped = True
    sources_created = 0

    for i, sq in enumerate(sub_questions, 1):
        # 创建子 step
        child_step = await _create_child_step(
            session, task, step, step_type="search",
            label=f"搜索子问题 {i}: {sq[:80]}",
        )
        child_step_id = str(child_step.id)

        # 发射子 step.started
        await sse_bridge.publish(EVENT_STEP_STARTED, {
            "step_id": child_step_id,
            "step_type": "search",
            "label": child_step.label,
            "parent_step_id": root_step_id,
        })

        try:
            results = await _search_one_sub_question(sq, i, api_key)
        except Exception as e:
            logger.warning("Search 子问题 %d 失败: %s", i, e)
            # 子 step → skipped
            await _finish_child_step(session, child_step, "skipped")
            await sse_bridge.publish(EVENT_STEP_SKIPPED, {
                "step_id": child_step_id,
                "reason": f"子问题 {i} 搜索失败: {e}",
            })
            sub_results.append({
                "sub_question": sq,
                "index": i,
                "results_count": 0,
                "status": "skipped",
                "step_id": child_step_id,
                "error": str(e),
            })
            continue

        results_count = len(results)
        await sse_bridge.publish(EVENT_STEP_PROGRESS, {
            "step_id": child_step_id,
            "results_found": results_count,
        })

        if results_count == 0:
            # 子 step → skipped（0 结果）
            await _finish_child_step(session, child_step, "skipped")
            await sse_bridge.publish(EVENT_STEP_SKIPPED, {
                "step_id": child_step_id,
                "reason": f"子问题 {i} 搜索返回 0 结果",
            })
            sub_results.append({
                "sub_question": sq,
                "index": i,
                "results_count": 0,
                "status": "skipped",
                "step_id": child_step_id,
            })
            continue

        # 标记为非全跳过
        all_skipped = False

        # 去重：保留首次出现的归属
        selected_results: list[dict] = []
        for r in results:
            url = r.get("url", "")
            if not url:
                continue
            if url in seen_urls:
                continue
            if len(selected_results) >= settings.TAVILY_MAX_RESULTS_PER_QUERY:
                break
            seen_urls.add(url)
            r["source_sub_question"] = sq
            r["sub_question_index"] = i
            selected_results.append(r)

        all_results.extend(selected_results)

        # 写入 ResearchSource 行（fetch_status=None，等待 Fetch 阶段填充）
        for r in selected_results:
            source = ResearchSource(
                task_id=task.id,
                url=r["url"],
                title=r.get("title", "")[:500],
                domain=_extract_domain(r["url"])[:255],
                fetch_status=None,
            )
            session.add(source)
            sources_created += 1

        await session.flush()

        # 子 step → completed
        child_output = {
            "sub_question": sq,
            "results_found": results_count,
            "selected": len(selected_results),
            "urls": [r["url"] for r in selected_results],
        }
        await _finish_child_step(session, child_step, "completed", child_output)
        await sse_bridge.publish(EVENT_STEP_COMPLETED, {
            "step_id": child_step_id,
            "results_count": results_count,
            "selected": len(selected_results),
        })

        sub_results.append({
            "sub_question": sq,
            "index": i,
            "results_count": results_count,
            "selected": len(selected_results),
            "status": "completed",
            "step_id": child_step_id,
        })

        # 总结果截断
        if len(all_results) >= settings.TAVILY_TOTAL_RESULTS_LIMIT:
            logger.info("Search 达到总结果上限 %d，停止搜索: task_id=%s", settings.TAVILY_TOTAL_RESULTS_LIMIT, task_id)
            break

    # 3. 全部失败检查
    if all_skipped and len(sub_results) > 0:
        raise SearchFailedException(
            detail=f"全部 {len(sub_results)} 个子问题搜索失败或返回 0 结果"
        )

    # 4. 更新 task 统计
    task.total_sources = (task.total_sources or 0) + sources_created
    await session.flush()

    # 去重后截断
    after_dedup = len(all_results)
    if after_dedup > settings.TAVILY_TOTAL_RESULTS_LIMIT:
        all_results = all_results[:settings.TAVILY_TOTAL_RESULTS_LIMIT]
        after_dedup = settings.TAVILY_TOTAL_RESULTS_LIMIT

    output = {
        "total_results": sum(sr.get("results_count", 0) for sr in sub_results),
        "after_dedup": after_dedup,
        "sub_question_results": sub_results,
        "sources_created": sources_created,
    }

    logger.info(
        "Search 完成: task_id=%s, total=%d, deduped=%d, sources=%d",
        task_id, output["total_results"], after_dedup, sources_created,
    )
    return output


# ── 辅助函数 ──────────────────────────────────────────────────


async def _load_sub_questions(
    session: AsyncSession,
    task: ResearchTask,
) -> list[str]:
    """从 Planning 阶段输出中提取 sub_questions。

    显式查询 research_steps 表，避免在 AsyncSession 中依赖 relationship 懒加载
    触发 MissingGreenlet。
    """
    stmt = (
        select(ResearchStep)
        .where(
            ResearchStep.task_id == task.id,
            ResearchStep.step_type == "planning",
            ResearchStep.status == "completed",
        )
        .order_by(ResearchStep.completed_at)
    )
    result = await session.execute(stmt)
    planning_step: ResearchStep | None = result.scalar_one_or_none()

    if planning_step and planning_step.output and isinstance(planning_step.output, dict):
        sqs = planning_step.output.get("sub_questions", [])
        if isinstance(sqs, list):
            return [str(sq) for sq in sqs if sq]

    return []


async def _create_child_step(
    session: AsyncSession,
    task: ResearchTask,
    parent_step: ResearchStep,
    step_type: str,
    label: str,
) -> ResearchStep:
    """创建子 ResearchStep。"""
    now = datetime.now(timezone.utc)
    child = ResearchStep(
        task_id=task.id,
        step_type=step_type,
        parent_step_id=parent_step.id,
        status="running",
        label=label,
        started_at=now,
    )
    session.add(child)
    await session.flush()
    return child


async def _finish_child_step(
    session: AsyncSession,
    child_step: ResearchStep,
    status: str,
    output: dict | None = None,
) -> None:
    """完成子 step（更新状态 + 耗时 + 输出）。"""
    now = datetime.now(timezone.utc)
    child_step.status = status
    child_step.completed_at = now
    if child_step.started_at:
        delta = now - child_step.started_at
        child_step.duration_ms = int(delta.total_seconds() * 1000)
    if output is not None:
        child_step.output = output
    # 更新 task 完成计数
    await session.flush()
