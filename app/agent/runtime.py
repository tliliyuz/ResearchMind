"""AgentRuntime —— Tool-Using Single Agent 对外主入口。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select as sa_select, update as sa_update
from sqlalchemy.orm import aliased

from app.agent.context import AgentContext
from app.agent.loop import AgentLoop, ToolExecutionResult
from app.agent.memory import ReActEntry, WorkingMemory
from app.agent.state import PhaseController
from app.config import settings
from app.core.cost_tracker import extract_step_cost
from app.core.exceptions import (
    extract_recoverable_from_exception,
    get_error_type,
    get_safe_error_message,
)
from app.core.task_state_resolver import TaskStateResolver
from app.core.trace_recorder import TraceRecorder
from app.models.enums import STEP_TYPE_ENUM
from app.models.research_step import ResearchStep
from app.models.research_task import ResearchTask
from app.pipeline.sse_bridge import (
    EVENT_CHECKPOINT_SAVED,
    EVENT_PHASE_COMPLETED,
    EVENT_PHASE_STARTED,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_STARTED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_FAILED,
    EVENT_TASK_PROGRESS,
    SSEBridge,
)
from app.services import agent_memory_service
from app.services.pipeline_orchestrator import (
    PHASE_ORDER,
    STEP_TYPE_TO_PHASE,
    build_default_phase_handlers,
)
from app.services.task_lifecycle import (
    TaskLockHandle,
    emergency_fail_task,
    load_task_steps,
    start_research_task,
)
from app.tools.base import Tool, ToolCall, ToolContext, ToolResult
from app.tools.registry import ToolRegistry, build_default_tool_registry

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Agent Runtime —— 替代 PipelineOrchestrator 的新调度器。"""

    def __init__(
        self,
        task: ResearchTask,
        session: Any,
        sse_bridge: SSEBridge,
        trace_recorder: TraceRecorder,
        tool_registry: ToolRegistry,
        max_iterations: int | None = None,
        working_memory_max_entries: int | None = None,
    ):
        self._task = task
        self._session = session
        self._sse = sse_bridge
        self._trace = trace_recorder
        self._registry = tool_registry
        self._max_iterations = max_iterations or settings.MAX_AGENT_ITERATIONS
        self._memory_max_entries = (
            working_memory_max_entries or settings.AGENT_WORKING_MEMORY_MAX_ENTRIES
        )

        self._resolver = TaskStateResolver()
        self._lock_handle = TaskLockHandle(str(task.id))
        self._agent_context: AgentContext | None = None
        self._working_memory: WorkingMemory | None = None
        self._phase_controller: PhaseController | None = None
        self._loop: AgentLoop | None = None

    @classmethod
    def build_default(
        cls,
        task: ResearchTask,
        session: Any,
        sse_bridge: SSEBridge,
        trace_recorder: TraceRecorder,
    ) -> "AgentRuntime":
        """使用默认 ToolRegistry 构建 AgentRuntime。"""
        registry = build_default_tool_registry()
        return cls(
            task=task,
            session=session,
            sse_bridge=sse_bridge,
            trace_recorder=trace_recorder,
            tool_registry=registry,
        )

    async def run(self) -> None:
        """执行 Agent Runtime。"""
        task_id = str(self._task.id)
        try:
            started = await start_research_task(
                self._task, self._session, self._sse, self._lock_handle
            )
            if not started:
                logger.warning("任务未成功启动，停止 Agent Runtime: task_id=%s", task_id)
                return

            self._agent_context, self._working_memory = await self._load_or_create_context()
            self._phase_controller = PhaseController(
                self._agent_context, self._registry
            )
            self._loop = AgentLoop(
                phase_controller=self._phase_controller,
                working_memory=self._working_memory,
                sse_bridge=self._sse,
                max_iterations=self._max_iterations,
            )

            tool_context = ToolContext(
                task=self._task,
                step=None,  # type: ignore[arg-type]
                session=self._session,
                sse_bridge=self._sse,
                trace_recorder=self._trace,
                agent_context=self._agent_context,
                working_memory=self._working_memory,
            )
            await self._loop.run(tool_context, self._execute_tool)

            # 捕获 loop 中非 tool 分支（LLM 失败 / 无 tool call）产生的 entries
            await self._persist_memory_entries()
            await self._finalize_task()

        except Exception as e:
            logger.exception("Agent Runtime 致命错误: task_id=%s, error=%s", task_id, e)
            await self._handle_fatal_error(e)
        finally:
            await self._lock_handle.release()

    async def _load_or_create_context(self) -> tuple[AgentContext, WorkingMemory]:
        """从 DB 或 execution_context 恢复或新建 AgentContext / WorkingMemory。"""
        execution_context = self._task.execution_context or {}
        agent_ctx_dict = execution_context.get("agent_context") if isinstance(execution_context, dict) else None

        agent_context = AgentContext.from_dict(agent_ctx_dict)
        # Phase 3：优先从 agent_memory_entries 表加载；DB 为空时 fallback 旧 JSON
        working_memory = await agent_memory_service.build_working_memory(
            self._session, str(self._task.id), max_entries=self._memory_max_entries
        )
        if not working_memory.recent():
            memory_items = execution_context.get("working_memory") if isinstance(execution_context, dict) else None
            working_memory = WorkingMemory.from_dict_list(
                memory_items, max_entries=self._memory_max_entries
            )
        return agent_context, working_memory

    async def _execute_tool(self, tool: Tool, tool_call: ToolCall) -> ToolExecutionResult:
        """AgentLoop 的 Tool 执行回调：创建 Step → 执行 Tool → 持久化。"""
        if tool.mapped_phase is None:
            # finish_tool 等无 phase 映射的 Tool，直接执行，不创建 Step
            result = await tool.execute(self._tool_context_with_step(None), **tool_call.arguments)
            return ToolExecutionResult(result=result, step_id=None)

        step = await self._create_step(tool.mapped_phase)
        await self._start_step(step)
        tool_context = self._tool_context_with_step(step)

        t0 = datetime.now(timezone.utc)
        try:
            result = await tool.execute(tool_context, **tool_call.arguments)
        except Exception as exc:  # noqa: BLE001
            result = ToolResult(
                success=False,
                output={},
                observation=f"{tool.mapped_phase} 阶段执行异常: {exc}",
                error_message=str(exc),
                duration_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
            )

        if result.success:
            await self._complete_step(step, result)
        else:
            await self._fail_step(step, result)

        return ToolExecutionResult(result=result, step_id=str(step.id))

    def _tool_context_with_step(self, step: ResearchStep | None) -> ToolContext:
        """构造包含指定 Step 的 ToolContext。"""
        return ToolContext(
            task=self._task,
            step=step,  # type: ignore[arg-type]
            session=self._session,
            sse_bridge=self._sse,
            trace_recorder=self._trace,
            agent_context=self._agent_context,  # type: ignore[arg-type]
            working_memory=self._working_memory,  # type: ignore[arg-type]
        )

    async def _create_step(self, step_type: str) -> ResearchStep:
        """创建当前 Tool 执行的 ResearchStep。"""
        step = ResearchStep(
            task_id=self._task.id,
            step_type=step_type,
            parent_step_id=self._agent_context.last_step_id,
            status="pending",
            label=self._phase_label(step_type),
        )
        self._session.add(step)
        await self._session.flush()
        return step

    async def _start_step(self, step: ResearchStep) -> None:
        """启动 Step：状态更新 + SSE。"""
        now = datetime.now(timezone.utc)
        step.status = "running"
        step.started_at = now
        await self._session.flush()

        phase_name = STEP_TYPE_TO_PHASE.get(step.step_type, step.step_type)
        previous_phase = self._task.current_phase
        self._task.current_phase = phase_name
        await self._session.flush()

        if previous_phase != phase_name:
            await self._sse.publish(EVENT_PHASE_STARTED, {
                "phase": phase_name,
                "timestamp": now.isoformat(),
            })

        await self._sse.publish(EVENT_STEP_STARTED, {
            "step_id": str(step.id),
            "step_type": step.step_type,
            "label": step.label,
            "timestamp": now.isoformat(),
        })

    async def _persist_memory_entries(self) -> None:
        """将 WorkingMemory 中待持久化 entries 写入 DB。"""
        if self._working_memory is None:
            return
        await agent_memory_service.persist_pending_entries(
            self._session, str(self._task.id), self._working_memory
        )

    async def _complete_step(self, step: ResearchStep, result: ToolResult) -> None:
        """Step 成功完成：写入 output、trace、SSE、checkpoint。"""
        now = datetime.now(timezone.utc)
        duration_ms = self._step_duration_ms(step, now)

        step.status = "completed"
        step.completed_at = now
        step.duration_ms = duration_ms
        step.output = result.output if isinstance(result.output, dict) else {"result": str(result.output)}
        step.cost = extract_step_cost(step.output, default_model=settings.LLM_MODEL)
        await self._session.flush()

        phase_name = STEP_TYPE_TO_PHASE.get(step.step_type, step.step_type)
        self._agent_context.last_step_id = str(step.id)
        # 在持久化 execution_context 前标记当前 phase 已完成，确保断点续跑状态一致
        self._agent_context.completed_phases.add(step.step_type)
        await self._record_phase_trace(step, duration_ms or 0, step.output)
        await self._update_execution_context(step, phase_name)
        await self._persist_memory_entries()
        await self._session.commit()

        await self._sse.publish(EVENT_STEP_COMPLETED, {
            "step_id": str(step.id),
            "output": step.output,
        })
        await self._sse.publish(EVENT_PHASE_COMPLETED, {
            "phase": phase_name,
            "duration_ms": duration_ms,
        })

        total = self._task.total_steps or 1
        completed = self._task.completed_steps or 0
        progress = round(completed / total, 2) if total > 0 else 0.0
        await self._sse.publish(EVENT_TASK_PROGRESS, {
            "completed_steps": completed,
            "total_steps": total,
            "progress": progress,
        })
        await self._sse.publish(EVENT_CHECKPOINT_SAVED, {
            "phase": phase_name,
            "last_completed_step_id": str(step.id),
            "saved_at": now.isoformat(),
        })

        logger.info(
            "Agent Step 完成: step_id=%s, type=%s, duration_ms=%s",
            step.id, step.step_type, duration_ms,
        )

    async def _fail_step(self, step: ResearchStep, result: ToolResult) -> None:
        """Step 失败：记录状态、SSE，不终止运行（除非后续被判定为 fatal）。"""
        now = datetime.now(timezone.utc)
        duration_ms = self._step_duration_ms(step, now)

        step.status = "failed"
        step.completed_at = now
        step.duration_ms = duration_ms
        step.error_message = result.error_message or "Tool 执行失败"
        await self._session.flush()

        await self._persist_memory_entries()

        await self._sse.publish(EVENT_STEP_FAILED, {
            "step_id": str(step.id),
            "error_type": "ToolExecutionFailed",
        })
        logger.warning(
            "Agent Step 失败: step_id=%s, type=%s, error=%s",
            step.id, step.step_type, result.error_message,
        )

    async def _update_execution_context(self, step: ResearchStep, phase_name: str) -> None:
        """更新 execution_context（包含 agent_context）。"""
        total = self._task.total_steps or 1

        terminal_statuses = {"completed", "skipped", "failed"}
        parent_step = aliased(ResearchStep)
        completed_result = await self._session.execute(
            sa_select(func.count())
            .select_from(ResearchStep)
            .outerjoin(
                parent_step,
                ResearchStep.parent_step_id == parent_step.id,
            )
            .where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type.in_(PHASE_ORDER),
                ResearchStep.status.in_(terminal_statuses),
            )
            .where(
                parent_step.id.is_(None) | (parent_step.step_type != ResearchStep.step_type)
            )
        )
        completed = completed_result.scalar() or 0
        self._task.completed_steps = completed

        progress = round(completed / total, 2) if total > 0 else 0.0
        progress = min(progress, 1.0)

        count_result = await self._session.execute(
            sa_select(func.count()).select_from(ResearchStep).where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type == step.step_type,
            )
        )
        phase_total = count_result.scalar() or 1

        completed_in_phase_result = await self._session.execute(
            sa_select(func.count()).select_from(ResearchStep).where(
                ResearchStep.task_id == self._task.id,
                ResearchStep.step_type == step.step_type,
                ResearchStep.status.in_(["completed", "skipped"]),
            )
        )
        phase_completed = completed_in_phase_result.scalar() or 0

        self._task.execution_context = {
            "current_phase": phase_name,
            "last_completed_step_id": str(step.id),
            "execution_pointer": {
                "phase": phase_name,
                "step_index": phase_completed,
                "total_steps_in_phase": phase_total,
            },
            "progress": {
                "completed_steps": completed,
                "total_steps": total,
                "progress": progress,
            },
            "agent_context": self._agent_context.to_dict(),
            # Phase 3：working_memory 不再写入 execution_context，唯一真实来源为 agent_memory_entries 表
        }
        await self._session.flush()

    async def _finalize_task(self) -> None:
        """全部 phase 完成后推导最终 Task State 并 CAS 写入。"""
        task_id = str(self._task.id)
        steps = await load_task_steps(self._session, task_id)
        evidence_count = self._task.total_evidence or 0

        new_status, error_info = self._resolver.resolve(
            self._task, steps, evidence_count,
        )

        # 记录任务结束 finish entry，使 agent_memory_entries 包含明确的终止标记
        if self._working_memory is not None and self._agent_context is not None:
            self._working_memory.add(ReActEntry(
                iteration=self._agent_context.iteration_count,
                phase="finish",
                tool_name="finish_tool",
                observation=f"Agent 结束运行，任务状态: {new_status}",
                tool_output_summary={"status": new_status},
            ))
            await self._persist_memory_entries()

        now = datetime.now(timezone.utc)
        trace_data = self._trace.finish()

        values: dict[str, Any] = {
            "status": new_status,
            "completed_at": now,
            "trace": trace_data,
        }
        if error_info:
            values["error_code"] = error_info.get("error_code")
            values["error_message"] = error_info.get("error_message")
            values["recoverable"] = error_info.get("recoverable", False)

        task_started_at = self._task.started_at
        task_total_sources = self._task.total_sources
        task_total_evidence = self._task.total_evidence
        execution_context = getattr(self._task, "execution_context", None)

        result = await self._session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task_id, ResearchTask.status == "running")
            .values(**values)
        )
        await self._session.commit()

        if result.rowcount == 0:
            await self._session.refresh(self._task, ["status"])
            logger.warning(
                "CAS 失败：最终化时任务状态已非 running: task_id=%s, current_status=%s",
                task_id, self._task.status,
            )
            return

        if new_status == "completed":
            await self._sse.publish(EVENT_TASK_COMPLETED, {
                "task_id": task_id,
                "status": "completed",
                "trace": {
                    "total_duration_ms": (
                        int((now - task_started_at).total_seconds() * 1000)
                        if task_started_at else 0
                    ),
                    "sources": task_total_sources or 0,
                    "evidence": task_total_evidence or 0,
                },
            })
        elif new_status == "partially_completed":
            await self._sse.publish(EVENT_TASK_COMPLETED, {
                "task_id": task_id,
                "status": "partially_completed",
                "trace": trace_data,
            })
        elif new_status == "failed":
            await self._sse.publish(EVENT_TASK_FAILED, {
                "task_id": task_id,
                "error_type": error_info.get("error_code", "Unknown") if error_info else "Unknown",
                "error_description": error_info.get("error_message", "") if error_info else "",
                "recoverable": error_info.get("recoverable", False) if error_info else False,
                "last_checkpoint": self._get_last_checkpoint(execution_context),
            })

        logger.info(
            "Agent Runtime 完成: task_id=%s, status=%s, steps=%d, evidence=%d",
            task_id, new_status, len(steps), evidence_count,
        )

    async def _handle_fatal_error(self, error: Exception) -> None:
        """处理未捕获致命错误：CAS 更新 task 为 failed。"""
        task_id = str(self._task.id)
        error_code = getattr(error, "error_code", None) or "E3999"
        error_msg = get_safe_error_message(error)
        error_type = get_error_type(error)
        recoverable = extract_recoverable_from_exception(error)

        try:
            trace_data = self._trace.finish()
        except Exception:
            logger.exception("Trace finish 失败: task_id=%s", task_id)
            trace_data = None

        try:
            result = await self._session.execute(
                sa_update(ResearchTask)
                .where(ResearchTask.id == task_id, ResearchTask.status == "running")
                .values(
                    status="failed",
                    completed_at=datetime.now(timezone.utc),
                    error_code=error_code,
                    error_message=error_msg,
                    recoverable=recoverable,
                    trace=trace_data,
                )
            )
            await self._session.commit()
            updated = result.rowcount > 0
        except Exception:
            logger.exception("写入失败状态时异常: task_id=%s", task_id)
            updated = False

        if updated:
            try:
                await self._sse.publish(EVENT_TASK_FAILED, {
                    "task_id": task_id,
                    "error_type": error_type,
                    "error_description": error_msg,
                    "recoverable": recoverable,
                })
            except Exception:
                logger.exception("SSE 发送失败: task_id=%s", task_id)

    async def _record_phase_trace(self, step: ResearchStep, duration_ms: int, output: dict[str, Any]) -> None:
        """按 phase 调用 TraceRecorder。"""
        step_type = step.step_type
        if step_type == "planning":
            self._trace.record_planning(
                duration_ms=duration_ms,
                input_tokens=output.get("prompt_tokens", 0),
                output_tokens=output.get("completion_tokens", 0),
                sub_questions_count=len(output.get("sub_questions", [])),
                retries=output.get("retry_count", 0),
                model=output.get("model"),
            )
        elif step_type == "search":
            sub_results = output.get("sub_question_results", [])
            total_results = output.get("total_results", 0)
            success_count = sum(1 for sr in sub_results if sr.get("status") == "completed")
            skipped_count = sum(1 for sr in sub_results if sr.get("status") == "skipped")
            self._trace.record_search(
                duration_ms=duration_ms,
                total_results=total_results,
                success_count=success_count,
                skipped_count=skipped_count,
                failed_count=0,
                cost_usd=output.get("search_cost_usd", 0.0),
            )
        elif step_type == "fetch":
            fetched = output.get("fetched", [])
            total_content_bytes = sum(
                item.get("content_length", 0) for item in fetched
                if isinstance(item.get("content_length"), int)
            )
            self._trace.record_fetch(
                duration_ms=duration_ms,
                total_urls=len(fetched),
                success_count=output.get("successful", 0),
                skipped_count=output.get("skipped_safety", 0),
                failed_count=output.get("failed", 0),
                total_content_bytes=total_content_bytes,
                cost_usd=output.get("fetch_cost_usd", 0.0),
            )
        elif step_type == "rerank":
            self._trace.record_rerank(
                duration_ms=duration_ms,
                bm25_candidates=output.get("bm25_candidates", 0),
                llm_reranked=output.get("evidence_count", 0),
                input_tokens=output.get("prompt_tokens", 0),
                output_tokens=output.get("completion_tokens", 0),
                retries=output.get("retry_count", 0),
                model=output.get("model"),
            )
        elif step_type == "synthesis":
            self._trace.record_synthesis(
                duration_ms=duration_ms,
                input_tokens=output.get("prompt_tokens", 0),
                output_tokens=output.get("completion_tokens", 0),
                clusters_count=output.get("clusters_count", 0),
                conflicts_count=output.get("conflicts_count", 0),
                knowledge_gaps_count=output.get("gaps_count", 0),
                retries=output.get("retry_count", 0),
                model=output.get("model"),
            )
        elif step_type == "evidence_graph":
            self._trace.record_evidence_graph(
                duration_ms=duration_ms,
                evidence_count=output.get("item_count", 0),
                source_count=output.get("source_count", 0),
            )
        elif step_type == "render":
            self._trace.record_render(
                duration_ms=duration_ms,
                input_tokens=output.get("prompt_tokens", 0),
                output_tokens=output.get("completion_tokens", 0),
                sections_count=output.get("sections_count", 0),
                citations_count=output.get("citations_count", 0),
                retries=output.get("retry_count", 0),
                model=output.get("model"),
            )

    @staticmethod
    def _phase_label(step_type: str) -> str:
        labels = {
            "planning": "Planning：拆解研究主题",
            "search": "Search：多子问题搜索",
            "fetch": "Fetch：网页内容抓取",
            "rerank": "Rerank：来源粗筛精排",
            "synthesis": "Synthesis：跨源综合",
            "evidence_graph": "来源图谱：结构化认知资产构建",
            "render": "Render：报告渲染",
        }
        return labels.get(step_type, step_type)

    @staticmethod
    def _step_duration_ms(step: ResearchStep, now: datetime) -> int | None:
        if step.started_at:
            return int((now - step.started_at).total_seconds() * 1000)
        return None

    @staticmethod
    def _get_last_checkpoint(execution_context: dict | None) -> str | None:
        if isinstance(execution_context, dict):
            last = execution_context.get("last_completed_step_id")
            if last:
                return str(last)
        return None
