"""TaskStateResolver 单元测试 — 覆盖所有 Task 状态推导分支。

对齐 ARCHITECTURE.md §3.7：
1. FATAL failure → FAILED
2. all COMPLETED → COMPLETED
3. partial with sufficient evidence → PARTIALLY_COMPLETED
4. partial with insufficient → FAILED (E3103)
"""

from unittest.mock import MagicMock

import pytest

from app.core.task_state_resolver import TaskStateResolver, FATAL_STEP_ERROR_CODES


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
        """证据 >= min_evidence → PARTIALLY_COMPLETED。"""
        task = _make_task(max_sources=10)  # min_evidence = max(5, ceil(10*0.4)) = 5
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code="E3104", error_message="Synthesis 失败"),  # recoverable
            _make_step("completed"),
            _make_step("skipped"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "partially_completed"
        assert err is None

    def test_部分失败_证据不足_返回failed_E3103(self):
        """证据 < min_evidence → FAILED E3103。"""
        task = _make_task(max_sources=10)  # min_evidence = 5
        steps = [
            _make_step("completed"),
            _make_step("failed", error_code="E3104", error_message="Synthesis 失败"),
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
            _make_step("failed", error_code="E3104"),
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
            _make_step("failed", error_code="E3104"),
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
            _make_step("failed", error_code="E3104"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=5)
        assert status == "partially_completed"

    def test_非致命失败_可恢复_降级判断(self):
        """E3104 (SynthesisFailed) → recoverable=True → 降级到 PARTIALLY_COMPLETED。"""
        task = _make_task()
        steps = [
            _make_step("completed"),
            _make_step("completed"),
            _make_step("failed", error_code="E3104", error_message="Synthesis 失败"),
        ]
        status, err = self.resolver.resolve(task, steps, evidence_count=6)
        assert status == "partially_completed"


# ═══════════════════════════════════════════════════════════════
# TestFatalStepErrorCodes
# ═══════════════════════════════════════════════════════════════


class TestFatalStepErrorCodes:
    """验证 FATAL_STEP_ERROR_CODES 常量完整性"""

    def test_包含全部5个不可恢复错误码(self):
        assert "E3101" in FATAL_STEP_ERROR_CODES  # PlanningFailed
        assert "E3102" in FATAL_STEP_ERROR_CODES  # SearchFailed（全部搜索失败→致命）
        assert "E3105" in FATAL_STEP_ERROR_CODES  # RerankFailed
        assert "E3106" in FATAL_STEP_ERROR_CODES  # EvidenceGraphBuildFailed
        assert "E3110" in FATAL_STEP_ERROR_CODES  # LLMAuthFailed

    def test_不包含可恢复错误码(self):
        assert "E3104" not in FATAL_STEP_ERROR_CODES  # SynthesisFailed → recoverable
        assert "E3107" not in FATAL_STEP_ERROR_CODES  # RenderFailed → recoverable
        assert "E3108" not in FATAL_STEP_ERROR_CODES  # LLMTimeout → recoverable
