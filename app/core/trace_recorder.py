"""Trace 数据收集器 — 轻量级，各阶段收集数据，finish() 一次性写入

对齐 RESEARCH_PIPELINE.md §11 成本追踪：
- 类结构：per-stage 计时 + JSON 字段 + context manager 模式
- 改阶段名称为 Pipeline 七阶段：
  Planning → Search → Fetch → Rerank → Synthesis → EvidenceGraph → Render
- MVP 不单独建 traces 表：trace 数据写入 research_tasks.trace JSON 列
- Trace 写入失败仅 log.warning，不阻塞主流程
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from app.core.cost_tracker import calculate_cost_usd

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串（用于 start_time）"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TraceRecorder:
    """Trace 数据收集器 — Pipeline 七阶段计时 + 成本追踪。

    在 Pipeline 执行开始时创建，各阶段调用 record_* 方法收集数据，
    流程结束时调用 finish() 返回 trace JSON（由调用方写入 research_tasks.trace）。

    使用方式：
        recorder = TraceRecorder(task_id, user_id, topic)
        # ... 各阶段埋点 ...
        recorder.record_planning(...)
        recorder.record_search(...)
        # ... 流程结束 ...
        trace_data = recorder.finish()
        task.trace = trace_data
        await db.commit()
    """

    # Pipeline 七阶段名称
    PHASES = [
        "planning",
        "search",
        "fetch",
        "rerank",
        "synthesis",
        "evidence_graph",
        "render",
    ]

    def __init__(
        self,
        task_id: str,
        user_id: int,
        topic: str,
        previous_trace: dict | None = None,
    ):
        self.task_id = task_id
        self.user_id = user_id
        self.topic = topic

        self._t_start = time.perf_counter()
        self._created_at = _utc_now_iso()
        self._status = "success"
        self._error_message: str | None = None

        # 各阶段 JSON 数据（None 表示未执行）
        self._planning_data: dict | None = None
        self._search_data: dict | None = None
        self._fetch_data: dict | None = None
        self._rerank_data: dict | None = None
        self._synthesis_data: dict | None = None
        self._evidence_graph_data: dict | None = None
        self._render_data: dict | None = None

        # Token / 成本聚合
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cost_usd: float = 0.0
        self._phase_cost: dict[str, dict[str, float | int]] = {}

        # 断点续跑：预加载 previous_trace 的阶段数据，供续跑中被跳过的阶段保留记录
        # _current_run_phases 记录当前运行中实际调用 record_* 的阶段，
        # finish() 时仅对这些阶段使用新数据，其余沿用 previous_trace。
        self._previous_trace: dict | None = (
            previous_trace if isinstance(previous_trace, dict) else None
        )
        self._current_run_phases: set[str] = set()
        self._merged: bool = False  # 防止 _merge_skipped_previous_phases 重复执行
        if self._previous_trace:
            self._preload_previous_phases()

    def _preload_previous_phases(self) -> None:
        """从 previous_trace 预加载各阶段数据到 _xxx_data 字段。

        续跑时这些阶段通常已被 Orchestrator 跳过（终态检查），
        因此 record_* 不会被调用，预加载数据将直接出现在 finish() 输出中。
        若某阶段被重新执行（如失败的 phase 重置后重跑），record_* 会覆盖预加载数据。
        """
        prev_phases = self._previous_trace.get("phases") or {}
        if not isinstance(prev_phases, dict):
            return
        for phase_name in self.PHASES:
            prev_data = prev_phases.get(phase_name)
            if isinstance(prev_data, dict):
                setattr(self, f"_{phase_name}_data", dict(prev_data))

    def _span_start_iso(self, t_span_start: float) -> str:
        """将 perf_counter 时间戳转换为 ISO 8601 字符串。"""
        offset_ms = (t_span_start - self._t_start) * 1000
        dt = datetime.fromisoformat(self._created_at) + timedelta(milliseconds=offset_ms)
        return dt.isoformat(timespec="milliseconds")

    def _accumulate_cost(
        self,
        phase: str,
        input_tokens: int,
        output_tokens: int,
        model: str | None,
    ) -> None:
        """累加 token 与成本到 task 总计与 phase breakdown。"""
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

        model_name = model or "unknown"
        cost_usd = calculate_cost_usd(input_tokens, output_tokens, model_name)
        self._total_cost_usd += cost_usd

        breakdown = self._phase_cost.setdefault(phase, {
            "tokens": 0,
            "cost": 0.0,
        })
        breakdown["tokens"] = int(breakdown["tokens"]) + input_tokens + output_tokens
        breakdown["cost"] = float(breakdown["cost"]) + cost_usd

    # ── 各阶段 record_* 方法 ──────────────────────────────

    def record_planning(
        self,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        sub_questions_count: int = 0,
        retries: int = 0,
        model: str | None = None,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Planning 阶段。"""
        self._current_run_phases.add("planning")
        self._planning_data = {
            "span_name": "planning",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "sub_questions_count": sub_questions_count,
            "retries": retries,
            "model": model,
        }
        self._accumulate_cost("planning", input_tokens, output_tokens, model)

    def record_search(
        self,
        duration_ms: float,
        total_results: int = 0,
        success_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
        cost_usd: float = 0.0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Search 阶段（Tavily API）。"""
        self._current_run_phases.add("search")
        self._search_data = {
            "span_name": "search",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success" if failed_count == 0 else "partial",
            "total_results": total_results,
            "success_count": success_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "cost_usd": round(cost_usd, 6),
        }
        self._total_cost_usd += cost_usd
        breakdown = self._phase_cost.setdefault("search", {"tokens": 0, "cost": 0.0})
        breakdown["cost"] = float(breakdown["cost"]) + cost_usd

    def record_fetch(
        self,
        duration_ms: float,
        total_urls: int = 0,
        success_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
        total_content_bytes: int = 0,
        cost_usd: float = 0.0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Fetch 阶段（HTTP 抓取 + 正文提取）。"""
        self._current_run_phases.add("fetch")
        self._fetch_data = {
            "span_name": "fetch",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success" if failed_count == 0 else "partial",
            "total_urls": total_urls,
            "success_count": success_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "total_content_bytes": total_content_bytes,
            "cost_usd": round(cost_usd, 6),
        }
        self._total_cost_usd += cost_usd
        breakdown = self._phase_cost.setdefault("fetch", {"tokens": 0, "cost": 0.0})
        breakdown["cost"] = float(breakdown["cost"]) + cost_usd

    def record_rerank(
        self,
        duration_ms: float,
        bm25_candidates: int = 0,
        llm_reranked: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        retries: int = 0,
        model: str | None = None,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Rerank 阶段（BM25 粗筛 + LLM 精排）。"""
        self._current_run_phases.add("rerank")
        self._rerank_data = {
            "span_name": "rerank",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success",
            "bm25_candidates": bm25_candidates,
            "llm_reranked": llm_reranked,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "retries": retries,
            "model": model,
        }
        self._accumulate_cost("rerank", input_tokens, output_tokens, model)

    def record_synthesis(
        self,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        clusters_count: int = 0,
        conflicts_count: int = 0,
        knowledge_gaps_count: int = 0,
        retries: int = 0,
        model: str | None = None,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Synthesis 阶段（跨源综合）。"""
        self._current_run_phases.add("synthesis")
        self._synthesis_data = {
            "span_name": "synthesis",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "clusters_count": clusters_count,
            "conflicts_count": conflicts_count,
            "knowledge_gaps_count": knowledge_gaps_count,
            "retries": retries,
            "model": model,
        }
        self._accumulate_cost("synthesis", input_tokens, output_tokens, model)

    def record_evidence_graph(
        self,
        duration_ms: float,
        evidence_count: int = 0,
        source_count: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Evidence Graph Build 阶段（纯程序化，无 LLM 调用）。"""
        self._current_run_phases.add("evidence_graph")
        self._evidence_graph_data = {
            "span_name": "evidence_graph",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success",
            "evidence_count": evidence_count,
            "source_count": source_count,
        }

    def record_render(
        self,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        sections_count: int = 0,
        citations_count: int = 0,
        retries: int = 0,
        model: str | None = None,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Report Render 阶段。"""
        self._current_run_phases.add("render")
        self._render_data = {
            "span_name": "render",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "sections_count": sections_count,
            "citations_count": citations_count,
            "retries": retries,
            "model": model,
        }
        self._accumulate_cost("render", input_tokens, output_tokens, model)

    # ── 错误与完成 ─────────────────────────────────────────

    def record_error(self, error_message: str, failed_phase: str | None = None) -> None:
        """记录 Pipeline 执行错误。

        Args:
            error_message: 错误描述
            failed_phase: 失败的阶段名称（如 'search'、'render'）
        """
        self._status = "error"
        self._error_message = error_message
        if failed_phase:
            # 标记失败阶段的状态
            phase_data = getattr(self, f"_{failed_phase}_data", None)
            if phase_data is not None:
                phase_data["status"] = "error"
                phase_data["error"] = error_message

    def _merge_skipped_previous_phases(self) -> None:
        """将 previous_trace 中"未被当前运行重新执行"的阶段贡献累加到 task 总计与 breakdown。

        - _current_run_phases 中的阶段已被 record_* 重新记录，跳过；
        - 其余阶段若有 previous_trace 数据，累加 tokens / cost 到 total_* 与 _phase_cost。

        仅在 finish() 中调用一次，_merged 标志防重入。
        """
        if not self._previous_trace or self._merged:
            return
        self._merged = True

        prev_phases = self._previous_trace.get("phases") or {}
        prev_breakdown = self._previous_trace.get("breakdown") or {}

        for phase_name in self.PHASES:
            if phase_name in self._current_run_phases:
                continue  # 当前运行已重新记录，沿用新数据
            prev_data = prev_phases.get(phase_name)
            if not isinstance(prev_data, dict):
                continue

            # 累加 tokens（LLM 阶段才有）
            in_tok = int(prev_data.get("input_tokens") or 0)
            out_tok = int(prev_data.get("output_tokens") or 0)
            self._total_input_tokens += in_tok
            self._total_output_tokens += out_tok

            # 累加 cost：search/fetch 使用 cost_usd 字段；LLM 阶段按 token+model 重算
            if "cost_usd" in prev_data:
                self._total_cost_usd += float(prev_data.get("cost_usd") or 0.0)
            elif in_tok or out_tok:
                model = prev_data.get("model") or "unknown"
                self._total_cost_usd += calculate_cost_usd(in_tok, out_tok, model)

            # 合并 breakdown
            prev_bd = prev_breakdown.get(phase_name)
            if isinstance(prev_bd, dict):
                cur = self._phase_cost.setdefault(phase_name, {"tokens": 0, "cost": 0.0})
                cur["tokens"] = int(cur["tokens"]) + int(prev_bd.get("tokens") or 0)
                cur["cost"] = float(cur["cost"]) + float(prev_bd.get("cost") or 0.0)

    def _build_trace_dict(self) -> dict:
        """构建当前 trace JSON dict（不执行 merge，纯读取当前状态）。

        token / cost 总计与 breakdown 均从各阶段 phase data 重新计算，
        而非使用内部累加器。这样在断点续跑场景下，preloaded 阶段的
        token/cost 也会被计入中间 snapshot，确保 checkpoint 持久化的 trace 数据完整。
        """
        total_input = 0
        total_output = 0
        total_cost = 0.0
        total_duration_ms = 0
        phase_durations = {}
        breakdown: dict[str, dict[str, float | int]] = {}

        for phase_name in self.PHASES:
            phase_data = getattr(self, f"_{phase_name}_data", None)
            if phase_data is None:
                continue

            duration_ms = int(phase_data.get("duration_ms") or 0)
            phase_durations[phase_name] = duration_ms
            total_duration_ms += duration_ms

            in_tok = int(phase_data.get("input_tokens") or 0)
            out_tok = int(phase_data.get("output_tokens") or 0)
            total_input += in_tok
            total_output += out_tok

            # 成本：search/fetch 使用 cost_usd 字段；LLM 阶段按 token+model 计算
            if "cost_usd" in phase_data:
                phase_cost = float(phase_data.get("cost_usd") or 0.0)
                total_cost += phase_cost
                breakdown[phase_name] = {"tokens": in_tok + out_tok, "cost": phase_cost}
            elif in_tok or out_tok:
                model = phase_data.get("model") or "unknown"
                phase_cost = calculate_cost_usd(in_tok, out_tok, model)
                total_cost += phase_cost
                breakdown[phase_name] = {"tokens": in_tok + out_tok, "cost": phase_cost}
            else:
                # evidence_graph 等无 token 无 cost 的阶段也记录入口
                breakdown[phase_name] = {"tokens": 0, "cost": 0.0}

        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "status": self._status,
            "total_duration_ms": total_duration_ms,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_cost_usd": round(total_cost, 6),
            "phases": {
                "planning": self._planning_data,
                "search": self._search_data,
                "fetch": self._fetch_data,
                "rerank": self._rerank_data,
                "synthesis": self._synthesis_data,
                "evidence_graph": self._evidence_graph_data,
                "render": self._render_data,
            },
            "phase_durations_ms": phase_durations,
            "breakdown": breakdown,
            "error_message": self._error_message,
            "created_at": self._created_at,
        }

    def snapshot(self) -> dict:
        """返回当前 trace 中间快照（供 checkpoint 持久化）。

        与 finish() 的区别：
        - 不调用 _merge_skipped_previous_phases()（merge 仅在最终化时执行一次）
        - 不修改任何内部状态，可多次安全调用

        断点续跑场景：每次 checkpoint 将 snapshot 写入 task.trace，
        Worker 崩溃后恢复时 previous_trace 即包含崩溃前已完成阶段的完整数据。
        """
        return self._build_trace_dict()

    def finish(self) -> dict:
        """计算总耗时，返回 trace JSON（供写入 research_tasks.trace）。

        断点续跑场景下：
        - 未在当前运行中重新执行（_current_run_phases 之外）但有 previous_trace 数据的阶段，
          其 tokens / cost 会被累加到 task 总计，breakdown 也会合并 previous_trace 的对应项。
        - 重新执行过的阶段以新数据为准，previous_trace 中对应项被丢弃。

        Returns:
            trace JSON dict，结构对齐 DATABASE.md §2.2 research_tasks.trace 列
        """
        # 续跑场景：补齐 skipped 阶段的 previous_trace 贡献到 task 总计与 breakdown
        if self._previous_trace:
            self._merge_skipped_previous_phases()

        trace = self._build_trace_dict()

        logger.info(
            "Trace 已收集: task_id=%s status=%s total_ms=%d phases=%d",
            self.task_id, self._status, trace["total_duration_ms"],
            sum(1 for v in trace["phases"].values() if v is not None),
        )

        return trace
