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

# ── 不可恢复（FATAL）的 Step 错误码 ────────────────────────────
# 这些错误一旦发生，任务无法通过断点续跑恢复，直接判定 FAILED。
# 定义来源：ARCHITECTURE.md §5.5 Failure Model + API.md §5.3
FATAL_STEP_ERROR_CODES = frozenset({
    "E3101",   # PlanningFailed — LLM 无法拆解研究主题
    "E3102",   # SearchFailed — Tavily API 完全不可用（全部搜索失败）
    "E3105",   # RerankFailed — Rerank 输入格式错误或计算失败
    "E3106",   # EvidenceGraphBuildFailed — Evidence Graph 构建失败
    "E3110",   # LLMAuthFailed — LLM 认证失败（重试无意义）
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

        # 2. 检查是否所有 Step 已完成
        if self._all_steps_terminal(steps):
            if self._all_non_skipped_completed(steps):
                return "completed", None
            # 部分完成 → Evidence Threshold 判定
            return self._evaluate_partial_completion(task, evidence_count)

        # 还有 Step 未终态 → 不应调用 resolve（调用方应等待全部 Step 终态）
        return task.status, None

    # ── 内部方法 ────────────────────────────────────────────────

    def _check_fatal(self, steps: list[Any]) -> dict | None:
        """检查是否存在 FATAL 错误。

        遍历所有 Step，若存在不可恢复的失败（错误码在 FATAL_STEP_ERROR_CODES 中），
        立即返回 error_info，不再评估 Evidence Threshold。
        """
        for step in steps:
            if step.status == "failed" and step.error_code in FATAL_STEP_ERROR_CODES:
                return {
                    "error_code": step.error_code,
                    "error_message": step.error_message or "致命错误，任务无法继续",
                    "recoverable": False,
                }
        return None

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
                    f"证据量不满足最小阈值：已收集 {evidence_count} 条，"
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
