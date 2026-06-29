"""Agent Memory Service —— ReAct Trace 的 DB 持久化层。

Phase 3 新增：将 WorkingMemory 中的 ReActEntry 持久化到 agent_memory_entries 表，
作为断点续跑与调试的可靠来源。

约定：本模块所有函数只执行 await db.flush()，不 commit；调用方控制事务边界。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory import ReActEntry, WorkingMemory
from app.models.agent_memory_entry import AgentMemoryEntry


def classify_react_entry(entry: ReActEntry) -> str:
    """根据 ReActEntry 字段推导 entry_type。

    分类优先级：finish > action > observation > thought。
    一个 ReActEntry 映射为一行 DB 记录，不拆分多行。
    """
    if entry.tool_name == "finish_tool":
        return "finish"
    if entry.tool_name is not None:
        return "action"
    if entry.observation is not None:
        return "observation"
    return "thought"


def _react_entry_to_memory_entry(
    task_id: str, entry: ReActEntry
) -> AgentMemoryEntry:
    """将 ReActEntry 转换为待持久化的 AgentMemoryEntry ORM 对象。"""
    content = entry.to_dict()
    # content 已包含完整字段；created_at 复用 entry.timestamp 保持时间线一致
    return AgentMemoryEntry(
        task_id=task_id,
        step_id=entry.step_id,
        iteration=entry.iteration,
        phase=entry.phase,
        entry_type=classify_react_entry(entry),
        content=content,
        created_at=entry.timestamp if isinstance(entry.timestamp, datetime) else datetime.now(timezone.utc),
    )


async def create_memory_entry(
    db: AsyncSession,
    task_id: str,
    entry: ReActEntry,
) -> AgentMemoryEntry:
    """将单条 ReActEntry 持久化为 AgentMemoryEntry。"""
    memory_entry = _react_entry_to_memory_entry(task_id, entry)
    db.add(memory_entry)
    await db.flush()
    return memory_entry


async def list_memory_entries(
    db: AsyncSession,
    task_id: str,
    *,
    limit: int | None = None,
    entry_type: str | None = None,
) -> list[AgentMemoryEntry]:
    """按任务查询 AgentMemoryEntry，默认按 created_at 升序返回。"""
    stmt = (
        sa_select(AgentMemoryEntry)
        .where(AgentMemoryEntry.task_id == task_id)
        .order_by(AgentMemoryEntry.created_at.asc())
    )
    if entry_type is not None:
        stmt = stmt.where(AgentMemoryEntry.entry_type == entry_type)
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def build_working_memory(
    db: AsyncSession,
    task_id: str,
    max_entries: int = 20,
) -> WorkingMemory:
    """从 DB 加载最近 max_entries 条 AgentMemoryEntry，重建 WorkingMemory。

    按 created_at DESC 取最近 N 条，再反转为时间线顺序注入 WorkingMemory。
    """
    stmt = (
        sa_select(AgentMemoryEntry)
        .where(AgentMemoryEntry.task_id == task_id)
        .order_by(AgentMemoryEntry.created_at.desc())
        .limit(max_entries)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    # 反转回时间线顺序
    rows.reverse()

    memory = WorkingMemory(max_entries=max_entries)
    for row in rows:
        content: dict[str, Any] = row.content or {}
        entry = ReActEntry.from_dict(content)
        # 用 DB 中的 step_id / created_at 覆盖旧 JSON 可能缺失的字段
        entry.step_id = row.step_id
        entry.timestamp = row.created_at
        # 已持久化的条目直接写入 _entries，不进入 pending 队列
        memory._entries.append(entry)
    if len(memory._entries) > memory._max_entries:
        memory._entries = memory._entries[-memory._max_entries :]
    return memory


async def persist_pending_entries(
    db: AsyncSession,
    task_id: str,
    working_memory: WorkingMemory,
) -> int:
    """将 WorkingMemory 中待持久化的 entries 批量写入 DB。

    Returns:
        实际持久化的条目数。
    """
    pending = working_memory.pending_entries()
    if not pending:
        return 0

    for entry in pending:
        db.add(_react_entry_to_memory_entry(task_id, entry))
    await db.flush()
    working_memory.mark_persisted()
    return len(pending)
