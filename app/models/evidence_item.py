"""
证据条目表 ORM 模型 —— evidence_items 表。

表结构严格遵循 [DATABASE.md §2](docs/DATABASE.md#2-表结构)。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._types import UTCDateTime


class EvidenceItem(Base):
    """证据条目表 —— 从来源中提取的证据片段，核心认知资产。"""

    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True,
    )
    task_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey("research_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_steps.id", ondelete="SET NULL"),
        default=None,
        server_default=sa.text("NULL"),
        comment="产生此证据的 Step（NULL = 非 Step 产生）",
    )

    content: Mapped[str] = mapped_column(
        sa.Text, nullable=False, comment="证据原文片段"
    )
    relevance_score: Mapped[float | None] = mapped_column(
        sa.DECIMAL(4, 3), default=None, server_default=sa.text("NULL"),
        comment="Rerank 相关性分数 (0.000-1.000)",
    )

    # ── 用于哪些章节 ──
    used_in_sections: Mapped[dict | None] = mapped_column(
        sa.JSON, default=None, server_default=sa.text("NULL"),
        comment='如 ["1", "2.1"]',
    )

    # ── [v2 预留] ──
    # claim_id: Mapped[str | None]
    # position_in_doc: Mapped[int | None]

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.current_timestamp(),
        nullable=False,
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
        sa.Index("idx_source", "source_id"),
        sa.Index("idx_score", "task_id", sa.text("relevance_score DESC")),
    )

    # ── 关联 ──
    task = relationship("ResearchTask", back_populates="evidence_items")
    source = relationship("ResearchSource", back_populates="evidence_items")
    step = relationship("ResearchStep", back_populates="evidence_items")
    sections = relationship(
        "ReportSection",
        secondary="section_evidence",
        back_populates="evidence_items",
    )

    def __repr__(self):
        return f"<EvidenceItem(id={self.id}, task_id={self.task_id}, score={self.relevance_score})>"
