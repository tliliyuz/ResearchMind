"""
报告章节表 ORM 模型 —— report_sections 表。

表结构严格遵循 [DATABASE.md §2](docs/DATABASE.md#2-表结构)。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._types import UTCDateTime

from app.core.database import Base


class ReportSection(Base):
    """报告章节表 —— 支持嵌套的章节树。"""

    __tablename__ = "report_sections"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True,
    )
    task_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_section_id: Mapped[int | None] = mapped_column(
        sa.Integer,
        sa.ForeignKey("report_sections.id", ondelete="CASCADE"),
        default=None,
        server_default=sa.text("NULL"),
        comment="父章节（支持嵌套）",
    )
    heading: Mapped[str] = mapped_column(
        sa.String(300), nullable=False,
    )
    content: Mapped[str] = mapped_column(
        MEDIUMTEXT, nullable=False, comment="Markdown 正文"
    )
    sort_order: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default=sa.text("0"), nullable=False,
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
        sa.Index("idx_parent", "parent_section_id"),
    )

    # ── 关联 ──
    task = relationship("ResearchTask", back_populates="report_sections")
    parent_section = relationship(
        "ReportSection", remote_side="ReportSection.id", backref="child_sections"
    )
    evidence_items = relationship(
        "EvidenceItem",
        secondary="section_evidence",
        back_populates="sections",
    )

    def __repr__(self):
        return f"<ReportSection(id={self.id}, heading={self.heading!r})>"
