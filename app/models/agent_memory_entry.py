"""Agent Memory Entries —— ReAct Trace 持久化表。

Phase 3 新增表，用于持久化单次任务内的 Thought / Action / Observation / Finish 记录，
作为 WorkingMemory 的断点续跑与调试来源。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._types import UTCDateTime, new_uuid
from app.models.enums import MEMORY_ENTRY_TYPE_ENUM


class AgentMemoryEntry(Base):
    """Agent ReAct Trace 单条记录表。"""

    __tablename__ = "agent_memory_entries"

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=new_uuid
    )
    task_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_steps.id", ondelete="SET NULL"),
        default=None,
        server_default=sa.text("NULL"),
        comment="关联 ResearchStep.id",
    )

    iteration: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, comment="Agent Loop 轮次"
    )
    phase: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, comment="所属 phase"
    )
    entry_type: Mapped[str] = mapped_column(
        sa.Enum(*MEMORY_ENTRY_TYPE_ENUM, name="agent_memory_entry_type"),
        nullable=False,
    )
    content: Mapped[dict] = mapped_column(
        sa.JSON, nullable=False, comment="ReActEntry 完整字段"
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.current_timestamp(),
        nullable=False,
    )

    # ── 索引 ──
    # idx_agent_memory_task: 按任务列出 entries
    # idx_agent_memory_task_created: 按任务 + 时间倒序，用于 build_working_memory 取最近 N 条
    # idx_agent_memory_task_iteration: 按任务 + 迭代次数查询
    __table_args__ = (
        sa.Index("idx_agent_memory_task", "task_id"),
        sa.Index("idx_agent_memory_task_created", "task_id", sa.text("created_at DESC")),
        sa.Index("idx_agent_memory_task_iteration", "task_id", "iteration"),
    )

    # ── 关联 ──
    task = relationship("ResearchTask", back_populates="agent_memory_entries")
    step = relationship("ResearchStep", back_populates="agent_memory_entries")

    def __repr__(self):
        return (
            f"<AgentMemoryEntry(id={self.id}, task_id={self.task_id}, "
            f"iteration={self.iteration}, phase={self.phase}, entry_type={self.entry_type})>"
        )
