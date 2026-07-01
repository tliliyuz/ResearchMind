"""ResearchMind Prometheus 可观测性模块。"""

from app.metrics.collector import MetricsCollector
from app.metrics.emitters import (
    emit_agent_loop_iteration,
    emit_llm_tokens,
    emit_phase_duration,
    emit_task_cost,
    emit_task_status_transition,
    set_celery_queue_length,
    set_celery_worker_tasks_active,
    set_celery_workers_active,
)
from app.metrics.registry import CONTENT_TYPE_LATEST, get_metrics_output

_collector: MetricsCollector | None = None


async def setup_metrics() -> None:
    """应用启动时初始化 metrics 后台采集器。"""
    global _collector
    if _collector is not None:
        return
    _collector = MetricsCollector()
    await _collector.start()


async def shutdown_metrics() -> None:
    """应用关闭时停止 metrics 后台采集器。"""
    global _collector
    if _collector is None:
        return
    await _collector.stop()
    _collector = None


__all__ = [
    "CONTENT_TYPE_LATEST",
    "MetricsCollector",
    "emit_agent_loop_iteration",
    "emit_llm_tokens",
    "emit_phase_duration",
    "emit_task_cost",
    "emit_task_status_transition",
    "get_metrics_output",
    "setup_metrics",
    "shutdown_metrics",
]
