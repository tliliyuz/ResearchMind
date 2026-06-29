"""Agent Runtime feature flag 集成测试。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import AgentContext
from app.agent.runtime import AgentRuntime
from app.core.llm import LLMResult, ToolCall
from app.core.trace_recorder import TraceRecorder
from app.models.agent_memory_entry import AgentMemoryEntry
from app.models.research_task import ResearchTask
from app.models.user import User
from app.pipeline.sse_bridge import (
    EVENT_AGENT_ACTION,
    EVENT_AGENT_OBSERVATION,
    EVENT_AGENT_THOUGHT,
    EVENT_CHECKPOINT_SAVED,
    EVENT_STEP_COMPLETED,
    EVENT_TASK_COMPLETED,
    SSEBridge,
)
from app.tools.memory_tool import MemoryTool
from app.tools.registry import ToolRegistry


class FakeRedis:
    def __init__(self):
        self.messages = []

    async def publish(self, channel, message):
        self.messages.append((channel, message))


class FakeSSEBridge:
    def __init__(self):
        self.events = []

    async def publish(self, event_type: str, data: dict | None = None) -> None:
        self.events.append({"event": event_type, "data": data or {}})


async def _stub_handler(task, step, session, sse):
    return {"ok": True, "prompt_tokens": 1, "completion_tokens": 1, "model": "test"}


@pytest.fixture
def agent_registry():
    handlers = {phase: _stub_handler for phase in AgentContext.from_dict({}).to_dict()["completed_phases"]}
    # 使用 7 phase 固定顺序
    from app.models.enums import STEP_TYPE_ENUM
    handlers = {phase: _stub_handler for phase in STEP_TYPE_ENUM}
    reg = ToolRegistry()
    from app.tools.base import PhaseHandlerTool
    for phase in STEP_TYPE_ENUM:
        reg.register(PhaseHandlerTool(
            name=f"{phase}_tool",
            description=f"tool for {phase}",
            mapped_phase=phase,
            handler=handlers[phase],
        ))
    reg.register(MemoryTool())
    return reg


class TestAgentRuntimeFlag:
    async def test_启用agent_runtime_完成7个phase(
        self,
        db_session: AsyncSession,
        seeded_user,
        agent_registry,
        monkeypatch,
    ):
        user, _ = seeded_user
        task = ResearchTask(
            id="agent-task-1",
            user_id=user.id,
            topic="test",
            requirements={"max_sources": 10},
            status="pending",
        )
        db_session.add(task)
        await db_session.flush()

        # 模拟 Redis
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.pipeline.sse_bridge.get_async_redis", AsyncMock(return_value=fake_redis))

        # 模拟 LLM：按顺序返回 7 个 phase 的 tool call，
        # 在 search phase 穿插一次 memory_tool，最后 finish
        from app.models.enums import STEP_TYPE_ENUM
        phase_order = list(STEP_TYPE_ENUM)
        tool_sequence = [f"{phase}_tool" for phase in phase_order]
        # 在 search 之后插入 memory_tool，验证全局 Tool 不破坏 phase 推进
        tool_sequence.insert(2, "memory_tool")
        tool_call_index = {"i": 0}

        async def fake_chat(messages, tools=None, tool_choice=None, **kwargs):
            idx = tool_call_index["i"]
            if idx < len(tool_sequence):
                tool_name = tool_sequence[idx]
                tool_call_index["i"] += 1
                return LLMResult(
                    content="",
                    reasoning_content=f"reasoning {tool_name}",
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    tool_calls=[ToolCall(id=str(idx), name=tool_name, arguments={})],
                )
            return LLMResult(
                content="",
                reasoning_content="done",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                tool_calls=[ToolCall(id="finish", name="finish_tool", arguments={})],
            )

        monkeypatch.setattr("app.agent.loop.chat_completion", fake_chat)

        # Mock 任务锁，避免 Redis 依赖
        monkeypatch.setattr("app.services.task_lifecycle.acquire_task_lock_async", AsyncMock(return_value=True))
        monkeypatch.setattr("app.services.task_lifecycle.release_task_lock_async", AsyncMock())
        monkeypatch.setattr("app.services.task_lifecycle.refresh_task_lock_async", AsyncMock(return_value=True))

        # 将 commit 重定向为 flush，避免污染共享的内存 SQLite 测试库
        monkeypatch.setattr(db_session, "commit", db_session.flush)

        sse = FakeSSEBridge()
        trace = TraceRecorder(task_id=task.id, user_id=user.id, topic=task.topic)
        runtime = AgentRuntime(
            task=task,
            session=db_session,
            sse_bridge=sse,
            trace_recorder=trace,
            tool_registry=agent_registry,
            max_iterations=20,
        )
        await runtime.run()

        await db_session.refresh(task)
        assert task.status == "completed"

        # 验证 7 个主 step 均 completed
        from app.services.task_lifecycle import load_task_steps
        steps = await load_task_steps(db_session, task.id)
        completed_steps = [s for s in steps if s.status == "completed"]
        completed_phases = {s.step_type for s in completed_steps}
        assert completed_phases == set(phase_order)

        # 验证 execution_context 包含 agent_context
        assert isinstance(task.execution_context, dict)
        agent_ctx = task.execution_context.get("agent_context", {})
        assert set(agent_ctx.get("completed_phases", [])) == set(phase_order)

        # 验证 SSE 事件
        event_types = [e["event"] for e in sse.events]
        assert EVENT_AGENT_THOUGHT in event_types
        assert EVENT_AGENT_ACTION in event_types
        assert EVENT_AGENT_OBSERVATION in event_types
        assert EVENT_STEP_COMPLETED in event_types
        assert EVENT_CHECKPOINT_SAVED in event_types
        assert EVENT_TASK_COMPLETED in event_types

        # 验证 memory_tool 曾被调用且不破坏 phase 推进
        memory_actions = [
            e for e in sse.events
            if e["event"] == EVENT_AGENT_ACTION and e["data"].get("tool_name") == "memory_tool"
        ]
        assert len(memory_actions) == 1
        assert task.status == "completed"

        # 验证 agent_memory_entries 已持久化
        result = await db_session.execute(
            sa_select(AgentMemoryEntry).where(AgentMemoryEntry.task_id == task.id)
        )
        memory_entries = result.scalars().all()
        entry_types = {e.entry_type for e in memory_entries}
        assert "action" in entry_types
        # action entry 同时包含 observation 内容
        action_entries = [e for e in memory_entries if e.entry_type == "action"]
        assert all(e.content.get("observation") is not None for e in action_entries)
        # 所有主 phase tool 调用都有 step_id（memory_tool 除外）
        phase_action_entries = [e for e in action_entries if e.content.get("tool_name") != "memory_tool"]
        assert len(phase_action_entries) == len(phase_order)
        assert all(e.step_id is not None for e in phase_action_entries)

        # 验证任务结束时写入了 finish entry
        finish_entries = [e for e in memory_entries if e.entry_type == "finish"]
        assert len(finish_entries) == 1
        assert finish_entries[0].content.get("tool_name") == "finish_tool"
        assert finish_entries[0].content.get("observation") == "Agent 结束运行，任务状态: completed"

    async def test_断点续跑从DB恢复WorkingMemory(
        self,
        db_session: AsyncSession,
        seeded_user,
        agent_registry,
        monkeypatch,
    ):
        user, _ = seeded_user
        task = ResearchTask(
            id="agent-task-resume-1",
            user_id=user.id,
            topic="test",
            requirements={"max_sources": 10},
            status="pending",
            execution_context={
                "agent_context": {
                    "current_phase": "render",
                    "completed_phases": ["planning", "search", "fetch", "rerank", "synthesis", "evidence_graph"],
                    "iteration_count": 6,
                    "last_step_id": None,
                }
            },
        )
        db_session.add(task)
        await db_session.flush()

        # 预置前 6 个 phase 的 completed steps，使 resume 后只剩 render
        from app.models.research_step import ResearchStep
        for phase in ["planning", "search", "fetch", "rerank", "synthesis", "evidence_graph"]:
            db_session.add(ResearchStep(
                task_id=task.id,
                step_type=phase,
                status="completed",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ))
        await db_session.flush()

        # 预置一条历史 memory entry，模拟断点续跑前已持久化的 ReAct Trace
        from app.services import agent_memory_service
        from app.agent.memory import ReActEntry
        await agent_memory_service.create_memory_entry(
            db_session, task.id,
            ReActEntry(iteration=1, phase="planning", thought="历史思考"),
        )
        await db_session.flush()

        # 模拟 Redis
        fake_redis = FakeRedis()
        monkeypatch.setattr("app.pipeline.sse_bridge.get_async_redis", AsyncMock(return_value=fake_redis))

        # 模拟 LLM：直接调用 render_tool 完成最后 phase
        async def fake_chat(messages, tools=None, tool_choice=None, **kwargs):
            return LLMResult(
                content="",
                reasoning_content="完成 render",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                tool_calls=[ToolCall(id="render", name="render_tool", arguments={})],
            )

        monkeypatch.setattr("app.agent.loop.chat_completion", fake_chat)

        # Mock 任务锁
        monkeypatch.setattr("app.services.task_lifecycle.acquire_task_lock_async", AsyncMock(return_value=True))
        monkeypatch.setattr("app.services.task_lifecycle.release_task_lock_async", AsyncMock())
        monkeypatch.setattr("app.services.task_lifecycle.refresh_task_lock_async", AsyncMock(return_value=True))

        # 将 commit 重定向为 flush
        monkeypatch.setattr(db_session, "commit", db_session.flush)

        sse = FakeSSEBridge()
        trace = TraceRecorder(task_id=task.id, user_id=user.id, topic=task.topic)
        runtime = AgentRuntime(
            task=task,
            session=db_session,
            sse_bridge=sse,
            trace_recorder=trace,
            tool_registry=agent_registry,
            max_iterations=10,
        )
        await runtime.run()

        await db_session.refresh(task)
        assert task.status == "completed"

        # 验证 DB 中既有历史 entry，也追加了新 entry
        result = await db_session.execute(
            sa_select(AgentMemoryEntry).where(AgentMemoryEntry.task_id == task.id)
        )
        memory_entries = result.scalars().all()
        thought_entries = [e for e in memory_entries if e.entry_type == "thought"]
        assert any(e.content.get("thought") == "历史思考" for e in thought_entries)
        # render_tool 对应的 action entry 携带 reasoning_content
        render_action = [e for e in memory_entries if e.entry_type == "action" and e.content.get("tool_name") == "render_tool"]
        assert len(render_action) == 1
        assert render_action[0].content.get("thought") == "完成 render"

        # 验证任务结束时写入了 finish entry
        finish_entries = [e for e in memory_entries if e.entry_type == "finish"]
        assert len(finish_entries) == 1
        assert finish_entries[0].content.get("tool_name") == "finish_tool"
