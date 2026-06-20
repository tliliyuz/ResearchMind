"""Trace 数据收集器 — 轻量级，各阶段收集数据，finish() 一次性写入

对齐 RESEARCH_PIPELINE.md §11 成本追踪：
- 从 DocMind 复制类结构（per-stage 计时 + JSON 字段 + context manager 模式）
- 改阶段名称为 Pipeline 七阶段：
  Planning → Search → Fetch → Rerank → Synthesis → EvidenceGraph → Render
- MVP 不单独建 traces 表：trace 数据写入 research_tasks.trace JSON 列
- Trace 写入失败仅 log.warning，不阻塞主流程
"""

import logging
import time
from datetime import datetime, timedelta, timezone

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

    def _span_start_iso(self, t_span_start: float) -> str:
        """将 perf_counter 时间戳转换为 ISO 8601 字符串。"""
        offset_ms = (t_span_start - self._t_start) * 1000
        dt = datetime.fromisoformat(self._created_at) + timedelta(milliseconds=offset_ms)
        return dt.isoformat(timespec="milliseconds")

    # ── 各阶段 record_* 方法 ──────────────────────────────

    def record_planning(
        self,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        sub_questions_count: int = 0,
        retries: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Planning 阶段。"""
        self._planning_data = {
            "span_name": "planning",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "sub_questions_count": sub_questions_count,
            "retries": retries,
        }
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

    def record_search(
        self,
        duration_ms: float,
        total_results: int = 0,
        success_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Search 阶段（Tavily API）。"""
        self._search_data = {
            "span_name": "search",
            "start_time": self._span_start_iso(t_span_start) if t_span_start else None,
            "duration_ms": int(duration_ms),
            "status": "success" if failed_count == 0 else "partial",
            "total_results": total_results,
            "success_count": success_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        }

    def record_fetch(
        self,
        duration_ms: float,
        total_urls: int = 0,
        success_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
        total_content_bytes: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Fetch 阶段（HTTP 抓取 + 正文提取）。"""
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
        }

    def record_rerank(
        self,
        duration_ms: float,
        bm25_candidates: int = 0,
        llm_reranked: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        retries: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Rerank 阶段（BM25 粗筛 + LLM 精排）。"""
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
        }
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

    def record_synthesis(
        self,
        duration_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        clusters_count: int = 0,
        conflicts_count: int = 0,
        knowledge_gaps_count: int = 0,
        retries: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Synthesis 阶段（跨源综合）。"""
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
        }
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

    def record_evidence_graph(
        self,
        duration_ms: float,
        evidence_count: int = 0,
        source_count: int = 0,
        t_span_start: float | None = None,
    ) -> None:
        """记录 Evidence Graph Build 阶段（纯程序化，无 LLM 调用）。"""
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
        t_span_start: float | None = None,
    ) -> None:
        """记录 Report Render 阶段。"""
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
        }
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

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

    def finish(self) -> dict:
        """计算总耗时，返回 trace JSON（供写入 research_tasks.trace）。

        Returns:
            trace JSON dict，结构对齐 DATABASE.md §2.2 research_tasks.trace 列
        """
        total_duration_ms = int((time.perf_counter() - self._t_start) * 1000)

        # 计算各阶段总耗时（仅含已执行阶段）
        phase_durations = {}
        for phase_name in self.PHASES:
            phase_data = getattr(self, f"_{phase_name}_data", None)
            if phase_data is not None:
                phase_durations[phase_name] = phase_data.get("duration_ms", 0)

        trace = {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "status": self._status,
            "total_duration_ms": total_duration_ms,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
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
            "error_message": self._error_message,
            "created_at": self._created_at,
        }

        logger.info(
            "Trace 已收集: task_id=%s status=%s total_ms=%d phases=%d",
            self.task_id, self._status, total_duration_ms,
            sum(1 for v in trace["phases"].values() if v is not None),
        )

        return trace
