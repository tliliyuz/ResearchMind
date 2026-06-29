"""
研究任务表 ORM 模型 —— research_tasks 表。

表结构严格遵循 [DATABASE.md §2](docs/DATABASE.md#2-表结构)。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._types import UTCDateTime, new_uuid
from app.models.enums import TASK_STATUS_ENUM, TASK_PHASE_ENUM


class ResearchTask(Base):
    """研究任务表 —— 一次完整的研究会话。"""

    __tablename__ = "research_tasks"

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=new_uuid
    )
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ── 输入 ──
    topic: Mapped[str] = mapped_column(
        sa.String(500), nullable=False, comment="用户输入的研究主题"
    )
    requirements: Mapped[dict] = mapped_column(
        sa.JSON, nullable=False, comment="研究要求（task_type, depth, max_sources, language...）"
    )

    # ── Level 1: Task State ──
    status: Mapped[str] = mapped_column(
        sa.Enum(*TASK_STATUS_ENUM, name="task_status"),
        default="pending",
        server_default=sa.text("'pending'"),
        nullable=False,
    )

    # ── Level 2: Phase State ──
    current_phase: Mapped[str | None] = mapped_column(
        sa.Enum(*TASK_PHASE_ENUM, name="task_phase"),
        default=None,
        server_default=sa.text("NULL"),
    )

    # ── Execution Context（断点续跑核心）──
    execution_context: Mapped[dict | None] = mapped_column(
        sa.JSON, default=None, server_default=sa.text("NULL"),
    )

    # ── 统计 ──
    total_steps: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"),
    )
    completed_steps: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"),
    )
    total_sources: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"),
    )
    total_evidence: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"),
    )

    # ── Trace 追踪数据 ──
    trace: Mapped[dict | None] = mapped_column(
        sa.JSON, default=None, server_default=sa.text("NULL"),
        comment="Pipeline 七阶段 Trace JSON（TraceRecorder.finish() 产出），对齐 DATABASE.md §2.2",
    )

    # ── 错误 ──
    error_code: Mapped[str | None] = mapped_column(
        sa.String(50), default=None, server_default=sa.text("NULL"),
    )
    error_message: Mapped[str | None] = mapped_column(
        sa.Text, default=None, server_default=sa.text("NULL"),
    )
    recoverable: Mapped[bool | None] = mapped_column(
        sa.Boolean, default=None, server_default=sa.text("NULL"),
        comment="是否可以断点续跑（NULL = 未失败）",
    )

    # ── 时间 ──
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.current_timestamp(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        default=None,
        server_default=sa.text("NULL"),
        comment="Worker 拾取时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        default=None,
        server_default=sa.text("NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
        comment="记录最后修改时间（ORM onupdate 维护）",
    )

    # ── 索引 ──
    # idx_user_created: 覆盖 get_task_list 的 WHERE user_id=? + ORDER BY created_at DESC，避免 filesort
    # idx_user_status_created: 覆盖带 status 筛选的 get_task_list，同样避免 filesort
    # idx_status: 保留，覆盖 startup recovery / evaluation loader 等 status-only 查询
    __table_args__ = (
        sa.Index("idx_status", "status"),
        sa.Index("idx_user_created", "user_id", sa.text("created_at DESC")),
        sa.Index("idx_user_status_created", "user_id", "status", sa.text("created_at DESC")),
    )

    # ── 关联 ──
    user = relationship("User", back_populates="research_tasks")
    steps = relationship("ResearchStep", back_populates="task", lazy="selectin",
                         order_by="ResearchStep.started_at",
                         passive_deletes=True)
    sources = relationship("ResearchSource", back_populates="task", lazy="selectin",
                           passive_deletes=True)
    evidence_items = relationship("EvidenceItem", back_populates="task", lazy="selectin",
                                  passive_deletes=True)
    report_sections = relationship("ReportSection", back_populates="task", lazy="selectin",
                                   passive_deletes=True)

    def __repr__(self):
        return f"<ResearchTask(id={self.id}, topic={self.topic[:30]!r}, status={self.status})>"
