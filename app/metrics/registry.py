"""Prometheus 指标注册中心。

使用独立的 CollectorRegistry，避免污染 prometheus_client 全局 REGISTRY，
便于测试隔离。多进程部署时通过 PROMETHEUS_MULTIPROC_DIR 环境变量启用
MultiProcessCollector 聚合。
"""

from __future__ import annotations

import os

# Windows 兼容：resource 模块缺少 getpagesize，但 prometheus_client 的
# process_collector 在导入时会调用。提供一个兜底值避免导入失败。
# process_collector 本身在 Windows 下不可用，本模块也不使用它。
try:
    import resource
    if not hasattr(resource, "getpagesize"):
        resource.getpagesize = lambda: 4096  # noqa: B010
except ImportError:
    pass

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

# ── 独立 Registry ─────────────────────────────────────────
REGISTRY = CollectorRegistry()

# 多进程模式：当 uvicorn 以多个 worker 启动时，必须设置 PROMETHEUS_MULTIPROC_DIR
# 环境变量，Prometheus 才能正确聚合各进程指标。
if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    multiprocess.MultiProcessCollector(REGISTRY)

# ── 任务级指标 ────────────────────────────────────────────

task_status_counter = Counter(
    "researchmind_task_status_total",
    "Task 状态转换次数",
    ["status", "recoverable"],
    registry=REGISTRY,
)

task_failure_counter = Counter(
    "researchmind_task_failures_total",
    "Task 失败按错误码分布",
    ["error_code"],
    registry=REGISTRY,
)

# ── Pipeline 阶段指标 ─────────────────────────────────────

phase_duration_histogram = Histogram(
    "researchmind_phase_duration_seconds",
    "Pipeline 阶段耗时",
    ["phase", "status"],
    buckets=[
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5,
        1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
    ],
    registry=REGISTRY,
)

# ── LLM / 成本指标 ────────────────────────────────────────

llm_tokens_counter = Counter(
    "researchmind_llm_tokens_total",
    "LLM Token 消耗",
    ["model", "token_type", "phase"],
    registry=REGISTRY,
)

task_cost_counter = Counter(
    "researchmind_task_cost_usd_total",
    "任务估算成本（美元）",
    ["model", "phase"],
    registry=REGISTRY,
)

# ── Agent Runtime 指标 ────────────────────────────────────

agent_loop_counter = Counter(
    "researchmind_agent_loop_iterations_total",
    "Agent Loop 迭代次数",
    ["phase", "outcome"],
    registry=REGISTRY,
)

# ── Celery / Worker 指标 ──────────────────────────────────

celery_queue_length = Gauge(
    "researchmind_celery_queue_length",
    "Celery 队列长度",
    ["queue"],
    registry=REGISTRY,
)

celery_workers_active = Gauge(
    "researchmind_celery_workers_active",
    "在线 Worker 数量",
    registry=REGISTRY,
)

celery_worker_tasks_active = Gauge(
    "researchmind_celery_worker_tasks_active",
    "Worker 当前活跃任务数",
    registry=REGISTRY,
)


# ── 输出 ──────────────────────────────────────────────────

def get_metrics_output() -> bytes:
    """生成 Prometheus 抓取格式的字节流。"""
    return generate_latest(REGISTRY)


# ── 测试辅助 ──────────────────────────────────────────────

def _reset_for_testing() -> None:
    """测试专用：将 Registry 中所有指标数值归零。

    仅用于单元测试隔离；生产代码禁止调用。
    """
    for metric in [
        task_status_counter,
        task_failure_counter,
        phase_duration_histogram,
        llm_tokens_counter,
        task_cost_counter,
        agent_loop_counter,
        celery_queue_length,
        celery_workers_active,
        celery_worker_tasks_active,
    ]:
        _reset_metric(metric)


def _reset_metric(metric) -> None:
    """递归归零一个指标（含带标签的子指标）。"""
    # 先递归处理带标签的子指标
    if hasattr(metric, "_metrics"):
        for child in metric._metrics.values():
            _reset_metric(child)

    if hasattr(metric, "_value"):
        metric._value.set(0)
    elif hasattr(metric, "_sum"):
        metric._sum.set(0)
        if hasattr(metric, "_buckets"):
            for bucket in metric._buckets:
                bucket.set(0)
