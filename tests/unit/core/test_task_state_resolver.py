"""TaskStateResolver 单元测试 — 覆盖所有 Task 状态推导分支。

对齐 ARCHITECTURE.md §3.7：
1. FATAL failure → FAILED
2. all COMPLETED → COMPLETED
3. partial with sufficient evidence → PARTIALLY_COMPLETED
4. partial with insufficient → FAILED (E3103)
"""

from unittest.mock import MagicMock

import pytest

from app.core.task_state_resolver import (
    TaskStateResolver,
    FATAL_STEP_ERROR_CODES,
    RECOVERABLE_STEP_ERROR_CODES,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


def _make_step(status="completed", error_code=None, error_message=None):
    """工厂函数：创建模拟 ResearchStep 对象。"""
    step = MagicMock()
    step.status = status
    step.error_code = error_code
    step.error_message = error_message
    return step


def _make_task(max_sources=10):
    """工厂函数：创建模拟 ResearchTask 对象。"""
    task = MagicMock()
    task.requirements = {"task_type": "analysis", "max_sources": max_sources}
    task.status = "running"
    return task


# ═══════════════════════════════════════════════════════════════
# TestTaskStateResolver
# ═══════════════════════════════════════════════════════════════


class TestTaskStateResolver:
    """Task 状态推导"""

    def setup_method(self):
        self.resolver = TaskStateResolver()

    # ── 全部成功 → COMPLETED ──────────────────────────────────

    def test_所有步骤completed_返回completed(self):
        task = _make_task()
        steps = [_make_step("completed") for _ in range(5)]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "completed"
        assert err is None

    def test_含skipped但其余completed_返回completed(self):
        """SKIPPED 是预期降级，不影响 COMPLETED 判定。"""
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("skipped"),
            _make_step("completed"),
            _make_step("completed"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "completed"
        assert err is None

    def test_全部skipped_返回failed_E3103(self):
        """全部 SKIPPED → 没有证据 → E3103。"""
        task = _make_task()
        steps = [_make_step("skipped") for _ in range(3)]
        status, err = self.resolver.resolve(task, steps, evidence_count=0)
        assert status == "failed"
        assert err is not None
        assert err["error_code"] == "E3103"
        assert err["recoverable"] is False

    # ── FATAL 失败 → FAILED ───────────────────────────────────

    def test_PlanningFailed_E3101_立即返回failed(self):
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code="E3101", error_message="LLM 无法拆解"),
            _make_step("completed"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "failed"
        assert err is not None
        assert err["error_code"] == "E3101"
        assert err["recoverable"] is False

    def test_RerankFailed_E3105_立即返回failed(self):
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("completed"),
            _make_step("failed", error_code="E3105", error_message="Rerank 失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "failed"
        assert err["error_code"] == "E3105"

    def test_EvidenceGraphFailed_E3106_立即返回failed(self):
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code="E3106", error_message="Graph 构建失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "failed"
        assert err["error_code"] == "E3106"

    def test_LLMAuthFailed_E3110_立即返回failed(self):
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code="E3110", error_message="API Key 无效"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "failed"
        assert err["error_code"] == "E3110"
        assert err["recoverable"] is False

    # ── 部分失败 → Evidence Threshold ─────────────────────────

    def test_部分失败_证据充足_返回partially_completed(self):
        """failed + error_code=None（可降级）且证据 >= min_evidence → PARTIALLY_COMPLETED。"""
        task = _make_task(max_sources=10)  # min_evidence = max(5, ceil(10*0.4)) = 5
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code=None, error_message="裸异常失败"),  # 可降级
            _make_step("completed"),
            _make_step("skipped"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "partially_completed"
        assert err is None

    def test_部分失败_证据不足_返回failed_E3103(self):
        """可降级失败但证据 < min_evidence → FAILED E3103。"""
        task = _make_task(max_sources=10)  # min_evidence = 5
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code=None, error_message="裸异常失败"),
            _make_step("skipped"),
            _make_step("skipped"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=2)
        assert status == "failed"
        assert err is not None
        assert err["error_code"] == "E3103"
        assert "2 条" in err["error_message"]

    def test_min_evidence下限为5(self):
        """max_sources 很小时，min_evidence 不低于 5。"""
        task = _make_task(max_sources=1)  # ceil(1*0.4)=1, max(5,1)=5
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code=None, error_message="裸异常失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=4)
        assert status == "failed"
        assert err["error_code"] == "E3103"

        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "partially_completed"

    def test_大max_sources_阈值按比例计算(self):
        """max_sources=50 → min_evidence = max(5, ceil(50*0.4)) = 20。"""
        task = _make_task(max_sources=50)
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code=None, error_message="裸异常失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=19)
        assert status == "failed"

        status, err = self.resolver.resolve(task, steps, evidence_count=20)
        assert status == "partially_completed"

    # ── 存在未终态 Step → 不推导 ──────────────────────────────

    def test_存在pending_返回原状态不推导(self):
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("pending"),
            _make_step("completed"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "running"  # 原状态不变

    def test_存在running_返回原状态(self):
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("running"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "running"

    # ── 边界情况 ──────────────────────────────────────────────

    def test_空步骤列表_返回原状态(self):
        task = _make_task()
        status, err = self.resolver.resolve(task, [], evidence_count=0)
        assert status == "running"

    def test_单个completed步骤(self):
        task = _make_task()
        steps = [_make_step("completed")]
        status, err = self.resolver.resolve(task, steps, evidence_count=0)
        assert status == "completed"

    def test_requirements为None_使用默认max_sources_10(self):
        task = _make_task()
        task.requirements = None
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code=None, error_message="裸异常失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "partially_completed"

    def test_非致命失败_error_code为None_证据充足_降级到partially_completed(self):
        """failed + error_code=None（裸异常，可降级）且证据充足 → PARTIALLY_COMPLETED。"""
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("completed"),
            _make_step("failed", error_code=None, error_message="裸异常失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=6)
        assert status == "partially_completed"
        assert err is None

    def test_Fatal失败_E3104_返回failed且recoverable为True(self):
        """E3104 (SynthesisFailed) 在 FATAL 集中，recoverable=True，直接 FAILED。"""
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code="E3104", error_message="Synthesis 失败"),
            _make_step("completed"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "failed"
        assert err is not None
        assert err["error_code"] == "E3104"
        assert err["recoverable"] is True

    def test_Fatal失败_E3101_返回failed且recoverable为False(self):
        """E3101 (PlanningFailed) 在 FATAL 集中，recoverable=False，直接 FAILED。"""
        task = _make_task()
        steps = [
            _make_step("failed", error_code="E3101", error_message="Planning 失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "failed"
        assert err is not None
        assert err["error_code"] == "E3101"
        assert err["recoverable"] is False

    def test_Fatal失败_脏error_message被清洗(self):
        """Step error_message 含 SQL/异常文本时，Resolver 返回的 error_info 应被清洗。"""
        task = _make_task()
        steps = [
            _make_step(
                "failed",
                error_code="E3102",
                error_message="Celery Worker 未捕获异常: [SQL: INSERT INTO research_sources ...]",
            ),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "failed"
        assert err["error_code"] == "E3102"
        assert err["error_message"] == "致命错误，任务无法继续"
        assert "SQL" not in err["error_message"]


# ═══════════════════════════════════════════════════════════════
# TestFatalStepErrorCodes
# ═══════════════════════════════════════════════════════════════


class TestFatalStepErrorCodes:
    """验证 FATAL_STEP_ERROR_CODES 常量完整性"""

    def test_包含全部致命停止错误码(self):
        """FATAL 集应包含全部 10 个 handler 抛出的 E31xx（E3103 由 Resolver 生成，不入集）。"""
        assert "E3101" in FATAL_STEP_ERROR_CODES  # PlanningFailed
        assert "E3102" in FATAL_STEP_ERROR_CODES  # SearchFailed
        assert "E3104" in FATAL_STEP_ERROR_CODES  # SynthesisFailed
        assert "E3105" in FATAL_STEP_ERROR_CODES  # RerankFailed
        assert "E3106" in FATAL_STEP_ERROR_CODES  # EvidenceGraphBuildFailed
        assert "E3107" in FATAL_STEP_ERROR_CODES  # RenderFailed
        assert "E3108" in FATAL_STEP_ERROR_CODES  # LLMTimeout
        assert "E3109" in FATAL_STEP_ERROR_CODES  # LLMRateLimit
        assert "E3110" in FATAL_STEP_ERROR_CODES  # LLMAuthFailed
        assert "E3111" in FATAL_STEP_ERROR_CODES  # LLMUnknown

    def test_不包含E3103_由resolver生成(self):
        """E3103 由 TaskStateResolver 在证据不足时生成，不应被 handler 抛出。"""
        assert "E3103" not in FATAL_STEP_ERROR_CODES

    def test_可恢复错误码集合完整(self):
        """RECOVERABLE 集对齐 API.md §5 recoverable 列。"""
        assert "E3102" in RECOVERABLE_STEP_ERROR_CODES
        assert "E3104" in RECOVERABLE_STEP_ERROR_CODES
        assert "E3107" in RECOVERABLE_STEP_ERROR_CODES
        assert "E3108" in RECOVERABLE_STEP_ERROR_CODES
        assert "E3109" in RECOVERABLE_STEP_ERROR_CODES
        assert "E3111" in RECOVERABLE_STEP_ERROR_CODES
        assert "E3101" not in RECOVERABLE_STEP_ERROR_CODES
        assert "E3103" not in RECOVERABLE_STEP_ERROR_CODES
        assert "E3105" not in RECOVERABLE_STEP_ERROR_CODES
        assert "E3106" not in RECOVERABLE_STEP_ERROR_CODES
        assert "E3110" not in RECOVERABLE_STEP_ERROR_CODES


# ═══════════════════════════════════════════════════════════════
# Phase-Aware 状态推导（Agent Runtime / 断点续跑）
# ═══════════════════════════════════════════════════════════════


def _make_phase_step(step_type: str, status="completed", error_code=None, error_message=None):
    """创建携带 phase 信息的模拟 ResearchStep。"""
    step = MagicMock()
    step.step_type = step_type
    step.status = status
    step.error_code = error_code
    step.error_message = error_message
    return step


class TestPhaseAwareResolver:
    """针对 Agent Runtime 与断点续跑场景的 phase-aware 推导。"""

    def setup_method(self):
        self.resolver = TaskStateResolver()

    def test_所有phase完成_存在同phase非终态重复step_仍返回completed(self):
        """已完成 phase 中的 pending/running 重复 Step（如 Agent Runtime 遗留）不应阻塞 completed。"""
        task = _make_task()
        steps = [
            _make_phase_step("planning", "completed"),
            _make_phase_step("search", "completed"),
            _make_phase_step("fetch", "completed"),
            _make_phase_step("rerank", "completed"),
            _make_phase_step("synthesis", "completed"),
            _make_phase_step("evidence_graph", "completed"),
            _make_phase_step("render", "completed"),
            # Agent Runtime 遗留的重复 render step，尚未进入终态
            _make_phase_step("render", "pending"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "completed"
        assert err is None

    def test_AgentRuntime中途_仅部分phase有step_返回running(self):
        """Agent Runtime 尚未推进到全部 phase 时，保持 running。"""
        task = _make_task()
        steps = [_make_phase_step("planning", "completed")]
        status, err = self.resolver.resolve(task, steps, evidence_count=0)
        assert status == "running"
        assert err is None

    def test_未completed_phase存在pending_step_返回running(self):
        """尚有未 completed 的 phase 存在非终态 Step → 继续运行。"""
        task = _make_task()
        steps = [
            _make_phase_step("planning", "completed"),
            _make_phase_step("search", "completed"),
            _make_phase_step("fetch", "completed"),
            _make_phase_step("rerank", "completed"),
            _make_phase_step("synthesis", "completed"),
            _make_phase_step("evidence_graph", "completed"),
            _make_phase_step("render", "running"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=10)
        assert status == "running"
        assert err is None

    def test_旧Pipeline存在skipped_phase_证据充足_返回partially_completed(self):
        """旧任务存在未实现的 skipped phase，但其余 phase 完成且证据充足 → partially_completed。"""
        task = _make_task(max_sources=10)  # min_evidence=5
        steps = [
            _make_phase_step("planning", "completed"),
            _make_phase_step("search", "completed"),
            _make_phase_step("fetch", "completed"),
            _make_phase_step("rerank", "completed"),
            _make_phase_step("synthesis", "completed"),
            _make_phase_step("evidence_graph", "skipped"),
            _make_phase_step("render", "completed"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "partially_completed"
        assert err is None

    def test_旧Pipeline存在skipped_phase_证据不足_返回failed_E3103(self):
        """skipped phase 导致无法完成全部 7 phase 且证据不足 → failed。"""
        task = _make_task(max_sources=10)
        steps = [
            _make_phase_step("planning", "completed"),
            _make_phase_step("search", "completed"),
            _make_phase_step("fetch", "completed"),
            _make_phase_step("rerank", "completed"),
            _make_phase_step("synthesis", "completed"),
            _make_phase_step("evidence_graph", "skipped"),
            _make_phase_step("render", "completed"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=0)
        assert status == "failed"
        assert err is not None
        assert err["error_code"] == "E3103"
