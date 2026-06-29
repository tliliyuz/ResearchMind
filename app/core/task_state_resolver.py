"""TaskStateResolver — 统一推导 Task 最终状态。

所有 Step 进入终态后触发，按以下优先级推导 Task 最终状态：

1. 存在 FAILED 且 failure_type = FATAL（不可恢复）？
   → Task = FAILED
2. 全部非 SKIPPED 的 Step 为 COMPLETED？
   → Task = COMPLETED
3. 存在 SKIPPED 或 FAILED（可降级）？
   → 统计 evidence_items 数量
      ├── >= min_evidence → PARTIALLY_COMPLETED
      └── < min_evidence  → FAILED (E3103 InsufficientEvidence)

详细定义见 ARCHITECTURE.md §3.7 和 §3.5。

**核心原则**：Task State **禁止**由 Task 自身直接写入，统一由本 Resolver 推导。
"""

import math
from typing import Any

from app.core.exceptions import sanitize_error_message_for_client
from app.models.enums import STEP_TYPE_ENUM

PHASE_ORDER = list(STEP_TYPE_ENUM)

# ── 致命停止（FATAL）的 Step 错误码 ────────────────────────────
# 这些错误一旦发生，Pipeline 立即停止，Task 判定 FAILED。
# 但"致命停止"≠"不可恢复"：recoverable 由异常自身携带，orchestrator 据实传播。
# 定义来源：ARCHITECTURE.md §5.5 Failure Model + API.md §5.3
FATAL_STEP_ERROR_CODES = frozenset({
    "E3101",   # PlanningFailed — LLM 无法拆解研究主题
    "E3102",   # SearchFailed — Tavily API 完全不可用（全部搜索失败）
    "E3104",   # SynthesisFailed — LLM 综合失败
    "E3105",   # RerankFailed — Rerank 输入格式错误或计算失败
    "E3106",   # EvidenceGraphBuildFailed — Evidence Graph 构建失败
    "E3107",   # RenderFailed — 报告渲染失败
    "E3108",   # LLMTimeout — LLM 调用超时
    "E3109",   # LLMRateLimit — LLM API 限流
    "E3110",   # LLMAuthFailed — LLM 认证失败（重试无意义）
    "E3111",   # LLMUnknown — LLM 调用返回未预期错误
})

# ── recoverable=true 的 Step 错误码（API.md §5 recoverable 列）────────────────
# 这些错误虽导致 Pipeline 致命停止，但用户可在修复外部原因后断点续跑 / 重试。
RECOVERABLE_STEP_ERROR_CODES = frozenset({
    "E3102",   # SearchFailed
    "E3104",   # SynthesisFailed
    "E3107",   # RenderFailed
    "E3108",   # LLMTimeout
    "E3109",   # LLMRateLimit
    "E3111",   # LLMUnknown
})


class TaskStateResolver:
    """研究任务状态推导器。

    由 Celery Worker 在每个 Step 完成后调用，根据所有 Step 的终态
    推导 Task 级状态。不直接写入状态 —— 调用方获取解析结果后执行
    CAS 更新（UPDATE ... WHERE status = 'old_value'）。

    Usage:
        resolver = TaskStateResolver()
        new_status, error_info = resolver.resolve(task, steps, evidence_count)
        if new_status != task.status:
            await update_task_status(task, new_status, error_info)
    """

    # ── 公开方法 ────────────────────────────────────────────────

    def resolve(
        self,
        task: Any,              # ResearchTask ORM 实例
        steps: list[Any],       # ResearchStep ORM 实例列表
        evidence_count: int,    # evidence_items 已收集数量
    ) -> tuple[str, dict | None]:
        """推导 Task 最终状态。

        Args:
            task: ResearchTask ORM 实例（需含 requirements JSON 字段）
            steps: 该任务的全部 ResearchStep 实例
            evidence_count: 已持久化的 evidence_items 行数

        Returns:
            (new_status: str, error_info: dict | None)
            - new_status: one of "completed" / "partially_completed" / "failed"
            - error_info: 仅在 status="failed" 时返回，含 error_code / error_message / recoverable
        """
        # 空步骤列表 → 不做推导，返回当前状态
        if not steps:
            return task.status, None

        # 1. 检查是否存在不可恢复的 FATAL 失败
        fatal_result = self._check_fatal(steps)
        if fatal_result:
            return "failed", fatal_result

        # 2. 是否携带 phase 信息
        has_phase_info = any(
            getattr(s, "step_type", None) in PHASE_ORDER for s in steps
        )

        if not has_phase_info:
            # 旧测试 / 旧数据：没有 step_type 时回退到原行为
            if not self._all_steps_terminal(steps):
                return task.status, None
            if self._all_non_skipped_completed(steps):
                return "completed", None
            return self._evaluate_partial_completion(task, evidence_count)

        # 3. 携带 phase 信息：区分「phase 未开始」「phase 已尝试但未完成」「已完成 phase 的重复 Step」
        completed_phases = self._get_completed_phases(steps)
        if completed_phases == set(PHASE_ORDER):
            return "completed", None

        attempted_phases = self._get_attempted_phases(steps)
        if attempted_phases != set(PHASE_ORDER):
            # 还有 phase 完全未产生 Step → 仍在运行中（Agent Runtime 中途 / Pipeline 未执行完）
            return task.status, None

        # 所有 phase 都已产生 Step，但部分 phase 没有 completed Step（failed / skipped）
        # 只有「未 completed phase」中的非终态 Step 才会阻塞；已完成 phase 的重复 Step 忽略
        blocking = self._blocking_uncompleted_steps(steps, completed_phases)
        if blocking:
            return task.status, None

        # 4. 到达终态但未能完成全部 7 phase → Evidence Threshold 判定
        return self._evaluate_partial_completion(task, evidence_count)

    # ── 内部方法 ────────────────────────────────────────────────

    def _check_fatal(self, steps: list[Any]) -> dict | None:
        """检查是否存在 FATAL 错误。

        遍历所有 Step，若存在致命停止的失败（错误码在 FATAL_STEP_ERROR_CODES 中），
        立即返回 error_info，不再评估 Evidence Threshold。
        recoverable 按异常自身定义传播（致命停止 ≠ 不可恢复）。
        """
        for step in steps:
            if step.status == "failed" and step.error_code in FATAL_STEP_ERROR_CODES:
                return {
                    "error_code": step.error_code,
                    "error_message": sanitize_error_message_for_client(
                        step.error_message, fallback="致命错误，任务无法继续"
                    ),
                    "recoverable": step.error_code in RECOVERABLE_STEP_ERROR_CODES,
                }
        return None

    @staticmethod
    def _get_completed_phases(steps: list[Any]) -> set[str]:
        """返回所有存在 completed Step 的 phase 集合。"""
        return {
            s.step_type
            for s in steps
            if s.status == "completed" and s.step_type in PHASE_ORDER
        }

    @staticmethod
    def _get_attempted_phases(steps: list[Any]) -> set[str]:
        """返回所有已经产生 Step 的 phase 集合（无论 Step 状态）。"""
        return {
            s.step_type
            for s in steps
            if getattr(s, "step_type", None) in PHASE_ORDER
        }

    @staticmethod
    def _all_steps_terminal(steps: list[Any]) -> bool:
        """所有 Step 是否均已进入终态。

        终态包括：completed / failed / skipped
        非终态：pending / running / retrying
        """
        terminal_statuses = {"completed", "failed", "skipped"}
        return all(s.status in terminal_statuses for s in steps)

    @staticmethod
    def _all_non_skipped_completed(steps: list[Any]) -> bool:
        """所有非 SKIPPED 的 Step 是否均为 COMPLETED。"""
        non_skipped = [s for s in steps if s.status != "skipped"]
        if not non_skipped:
            return False  # 全部 skipped → 不算 completed
        return all(s.status == "completed" for s in non_skipped)

    @staticmethod
    def _blocking_uncompleted_steps(steps: list[Any], completed_phases: set[str]) -> list[Any]:
        """返回阻止任务进入终态的非终态 Step。

        仅统计「所属 phase 尚未 completed」的 Step；
        已完成 phase 中的非终态重复 Step（如 Agent Runtime 遗留）不阻塞。
        """
        terminal_statuses = {"completed", "failed", "skipped"}
        return [
            s for s in steps
            if getattr(s, "step_type", None) in PHASE_ORDER
            and s.step_type not in completed_phases
            and s.status not in terminal_statuses
        ]

    def _evaluate_partial_completion(
        self, task: Any, evidence_count: int
    ) -> tuple[str, dict | None]:
        """部分完成 → Evidence Completeness Threshold 判定。

        min_evidence = max(5, ceil(max_sources * 0.4))
        - evidence_count >= min_evidence → PARTIALLY_COMPLETED
        - evidence_count <  min_evidence → FAILED (E3103)

        阈值定义来源：ARCHITECTURE.md §3.5
        """
        max_sources = self._get_max_sources(task)
        min_evidence = max(5, math.ceil(max_sources * 0.4))

        if evidence_count >= min_evidence:
            return "partially_completed", None
        else:
            return "failed", {
                "error_code": "E3103",
                "error_message": (
                    f"来源量不满足最小阈值：已收集 {evidence_count} 条，"
                    f"要求 >= {min_evidence} 条（max_sources={max_sources}）"
                ),
                "recoverable": False,
            }

    @staticmethod
    def _get_max_sources(task: Any) -> int:
        """从 task.requirements 中安全提取 max_sources。"""
        try:
            req = task.requirements
            if isinstance(req, dict):
                return int(req.get("max_sources", 10))
        except (TypeError, ValueError, AttributeError):
            pass
        return 10
