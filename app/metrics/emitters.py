"""业务埋点函数。

所有 emit 函数均为「失败安全」：埋点异常只记 warning，不向调用方抛异常，
避免监控代码影响主业务路径。
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.metrics.registry import (
    agent_loop_counter,
    celery_queue_length,
    celery_worker_tasks_active,
    celery_workers_active,
    llm_tokens_counter,
    phase_duration_histogram,
    task_cost_counter,
    task_failure_counter,
    task_status_counter,
)

logger = logging.getLogger(__name__)


def _safe_label(value: Any) -> str:
    """将任意值转换为合法的 Prometheus label 字符串。"""
    if value is None:
        return ""
    return str(value)


def emit_task_status_transition(
    status: str,
    recoverable: bool | None = None,
    error_code: str | None = None,
) -> None:
    """记录任务状态转换。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        task_status_counter.labels(
            status=_safe_label(status),
            recoverable=_safe_label(recoverable),
        ).inc()
        if status == "failed" and error_code:
            task_failure_counter.labels(error_code=_safe_label(error_code)).inc()
    except Exception:
        logger.warning("埋点 task_status_transition 失败", exc_info=True)


def emit_phase_duration(phase: str, duration_ms: int, status: str) -> None:
    """记录 Pipeline 阶段耗时（毫秒转换为秒）。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        seconds = (duration_ms or 0) / 1000.0
        phase_duration_histogram.labels(
            phase=_safe_label(phase),
            status=_safe_label(status),
        ).observe(seconds)
    except Exception:
        logger.warning("埋点 phase_duration 失败", exc_info=True)


def emit_llm_tokens(model: str, prompt_tokens: int, completion_tokens: int, phase: str) -> None:
    """记录 LLM Token 消耗。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        model_label = _safe_label(model) or "unknown"
        phase_label = _safe_label(phase)
        llm_tokens_counter.labels(
            model=model_label,
            token_type="prompt",
            phase=phase_label,
        ).inc(prompt_tokens or 0)
        llm_tokens_counter.labels(
            model=model_label,
            token_type="completion",
            phase=phase_label,
        ).inc(completion_tokens or 0)
    except Exception:
        logger.warning("埋点 llm_tokens 失败", exc_info=True)


def emit_task_cost(model: str, cost_usd: float, phase: str) -> None:
    """记录任务估算成本（美元）。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        task_cost_counter.labels(
            model=_safe_label(model) or "unknown",
            phase=_safe_label(phase),
        ).inc(cost_usd or 0.0)
    except Exception:
        logger.warning("埋点 task_cost 失败", exc_info=True)


def emit_agent_loop_iteration(phase: str, outcome: str) -> None:
    """记录 Agent Loop 单次迭代。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        agent_loop_counter.labels(
            phase=_safe_label(phase),
            outcome=_safe_label(outcome),
        ).inc()
    except Exception:
        logger.warning("埋点 agent_loop_iteration 失败", exc_info=True)


def set_celery_queue_length(queue: str, length: int) -> None:
    """设置 Celery 队列长度 Gauge。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        celery_queue_length.labels(queue=_safe_label(queue)).set(length)
    except Exception:
        logger.warning("埋点 celery_queue_length 失败", exc_info=True)


def set_celery_workers_active(count: int) -> None:
    """设置在线 Worker 数量 Gauge。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        celery_workers_active.set(count)
    except Exception:
        logger.warning("埋点 celery_workers_active 失败", exc_info=True)


def set_celery_worker_tasks_active(count: int) -> None:
    """设置 Worker 当前活跃任务数 Gauge。"""
    if not settings.METRICS_ENABLED:
        return
    try:
        celery_worker_tasks_active.set(count)
    except Exception:
        logger.warning("埋点 celery_worker_tasks_active 失败", exc_info=True)
