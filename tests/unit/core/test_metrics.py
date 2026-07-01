"""app/metrics 模块单元测试 — 验证指标注册、埋点函数与失败安全。"""

from unittest.mock import MagicMock, patch

import pytest

from app.metrics import (
    emit_agent_loop_iteration,
    emit_llm_tokens,
    emit_phase_duration,
    emit_task_cost,
    emit_task_status_transition,
    set_celery_queue_length,
    set_celery_worker_tasks_active,
    set_celery_workers_active,
)
from app.metrics.registry import REGISTRY


class TestRegistry:
    """指标对象注册"""

    def test_核心指标已注册(self):
        # REGISTRY.collect() 返回 metric family 名称（Counter 不含 _total 后缀）
        names = {
            "researchmind_task_status",
            "researchmind_task_failures",
            "researchmind_phase_duration_seconds",
            "researchmind_llm_tokens",
            "researchmind_task_cost_usd",
            "researchmind_agent_loop_iterations",
            "researchmind_celery_queue_length",
            "researchmind_celery_workers_active",
            "researchmind_celery_worker_tasks_active",
        }
        registered = {m.name for m in REGISTRY.collect()}
        assert names.issubset(registered)


class TestEmitTaskStatusTransition:
    """任务状态转换埋点"""

    def test_pending状态计数增加(self):
        emit_task_status_transition("pending")
        value = REGISTRY.get_sample_value(
            "researchmind_task_status_total",
            {"status": "pending", "recoverable": ""},
        )
        assert value == 1.0

    def test_failed状态携带recoverable和error_code(self):
        emit_task_status_transition("failed", recoverable=True, error_code="E3999")

        status_value = REGISTRY.get_sample_value(
            "researchmind_task_status_total",
            {"status": "failed", "recoverable": "True"},
        )
        assert status_value == 1.0

        failure_value = REGISTRY.get_sample_value(
            "researchmind_task_failures_total",
            {"error_code": "E3999"},
        )
        assert failure_value == 1.0


class TestEmitPhaseDuration:
    """Pipeline 阶段耗时埋点"""

    def test_成功阶段写入histogram(self):
        emit_phase_duration("planning", 1500, "success")

        count = REGISTRY.get_sample_value(
            "researchmind_phase_duration_seconds_count",
            {"phase": "planning", "status": "success"},
        )
        sum_value = REGISTRY.get_sample_value(
            "researchmind_phase_duration_seconds_sum",
            {"phase": "planning", "status": "success"},
        )
        assert count == 1.0
        assert sum_value == 1.5

    def test_失败阶段写入histogram(self):
        emit_phase_duration("fetch", 500, "failed")

        count = REGISTRY.get_sample_value(
            "researchmind_phase_duration_seconds_count",
            {"phase": "fetch", "status": "failed"},
        )
        assert count == 1.0


class TestEmitLLMTokens:
    """LLM Token 消耗埋点"""

    def test_prompt和completion分别计数(self):
        emit_llm_tokens("deepseek-v4-pro", 100, 50, "planning")

        prompt = REGISTRY.get_sample_value(
            "researchmind_llm_tokens_total",
            {"model": "deepseek-v4-pro", "token_type": "prompt", "phase": "planning"},
        )
        completion = REGISTRY.get_sample_value(
            "researchmind_llm_tokens_total",
            {"model": "deepseek-v4-pro", "token_type": "completion", "phase": "planning"},
        )
        assert prompt == 100.0
        assert completion == 50.0


class TestEmitTaskCost:
    """任务成本埋点"""

    def test_成本累加(self):
        emit_task_cost("deepseek-v4-pro", 0.05, "planning")
        emit_task_cost("deepseek-v4-pro", 0.03, "planning")

        value = REGISTRY.get_sample_value(
            "researchmind_task_cost_usd_total",
            {"model": "deepseek-v4-pro", "phase": "planning"},
        )
        assert value == 0.08


class TestEmitAgentLoopIteration:
    """Agent Loop 迭代埋点"""

    def test_迭代次数累加(self):
        emit_agent_loop_iteration("planning", "iteration")
        emit_agent_loop_iteration("planning", "iteration")

        value = REGISTRY.get_sample_value(
            "researchmind_agent_loop_iterations_total",
            {"phase": "planning", "outcome": "iteration"},
        )
        assert value == 2.0


class TestCeleryGauges:
    """Celery/Worker Gauge 埋点"""

    def test_队列长度gauge(self):
        set_celery_queue_length("research_task", 7)
        value = REGISTRY.get_sample_value(
            "researchmind_celery_queue_length",
            {"queue": "research_task"},
        )
        assert value == 7.0

    def test_worker在线数gauge(self):
        set_celery_workers_active(3)
        value = REGISTRY.get_sample_value("researchmind_celery_workers_active")
        assert value == 3.0

    def test_worker活跃任务数gauge(self):
        set_celery_worker_tasks_active(5)
        value = REGISTRY.get_sample_value("researchmind_celery_worker_tasks_active")
        assert value == 5.0


class TestEmittersFailSafe:
    """埋点函数失败安全 — 不抛异常"""

    @patch("app.metrics.emitters.task_status_counter")
    def test_counter抛异常时不传播(self, mock_counter):
        mock_counter.labels.side_effect = RuntimeError("boom")
        # 应静默 swallow，不抛异常
        emit_task_status_transition("pending")

    @patch("app.metrics.emitters.phase_duration_histogram")
    def test_histogram抛异常时不传播(self, mock_histogram):
        mock_histogram.labels.side_effect = RuntimeError("boom")
        emit_phase_duration("planning", 1000, "success")
