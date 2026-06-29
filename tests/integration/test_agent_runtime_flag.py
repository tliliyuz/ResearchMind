"""Agent Runtime feature flag 集成测试。"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import AgentContext
from app.agent.runtime import AgentRuntime
from app.core.llm import LLMResult, ToolCall
from app.core.trace_recorder import TraceRecorder
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
