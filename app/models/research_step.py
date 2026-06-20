"""
研究步骤表 ORM 模型 —— research_steps 表。

表结构严格遵循 [DATABASE.md §2](docs/DATABASE.md#2-表结构)。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._types import UTCDateTime, new_uuid
from app.models.enums import STEP_TYPE_ENUM, STEP_STATUS_ENUM


class ResearchStep(Base):
    """研究步骤表 —— DAG 执行树的节点（v1.0 线性 Tree，v2.0 真 DAG）。"""

    __tablename__ = "research_steps"

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=new_uuid
    )
    task_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_type: Mapped[str] = mapped_column(
        sa.Enum(*STEP_TYPE_ENUM, name="step_type"),
        nullable=False,
    )
    parent_step_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_steps.id", ondelete="SET NULL"),
        default=None,
        server_default=sa.text("NULL"),
        comment="DAG 边：父步骤",
    )

    # ── Level 3: Step State ──
    status: Mapped[str] = mapped_column(
        sa.Enum(*STEP_STATUS_ENUM, name="step_status"),
        default="pending",
        server_default=sa.text("'pending'"),
        nullable=False,
    )

    # ── 标签（前端展示用）──
    label: Mapped[str | None] = mapped_column(
        sa.String(200), default=None, server_default=sa.text("NULL"),
        comment='如 "搜索子问题 2：NIST PQC 标准进展"',
    )

    # ── 输入输出 ──
    input: Mapped[dict | None] = mapped_column(
        sa.JSON, default=None, server_default=sa.text("NULL"),
        comment="Step 输入参数",
    )
    output: Mapped[dict | None] = mapped_column(
        sa.JSON, default=None, server_default=sa.text("NULL"),
        comment="Step 产出",
    )

    # ── 重试 ──
    retry_count: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"),
    )
    max_retries: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"),
        comment="0 = 使用阶段默认值",
    )

    # ── 错误 ──
    error_code: Mapped[str | None] = mapped_column(
        sa.String(50), default=None, server_default=sa.text("NULL"),
    )
    error_message: Mapped[str | None] = mapped_column(
        sa.Text, default=None, server_default=sa.text("NULL"),
    )

    # ── 性能 ──
    duration_ms: Mapped[int | None] = mapped_column(
        sa.Integer, default=None, server_default=sa.text("NULL"),
        comment="执行耗时（毫秒）",
    )

    # ── 时间 ──
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        default=None,
        server_default=sa.text("NULL"),
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
    )

    # ── 索引 ──
    __table_args__ = (
        sa.Index("idx_task", "task_id"),
        sa.Index("idx_parent", "parent_step_id"),
        sa.Index("idx_task_status", "task_id", "status"),
    )

    # ── 关联 ──
    task = relationship("ResearchTask", back_populates="steps")
    parent_step = relationship(
        "ResearchStep", remote_side="ResearchStep.id", backref="child_steps"
    )
    evidence_items = relationship("EvidenceItem", back_populates="step", lazy="selectin")

    def __repr__(self):
        return f"<ResearchStep(id={self.id}, type={self.step_type}, status={self.status})>"
