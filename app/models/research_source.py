"""
来源表 ORM 模型 —— research_sources 表。

表结构严格遵循 [DATABASE.md §2](docs/DATABASE.md#2-表结构)。
"""

from datetime import datetime

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._types import UTCDateTime
from app.models.enums import FETCH_STATUS_ENUM


class ResearchSource(Base):
    """来源表 —— 记录抓取的所有网页来源。id 自增 = 报告引用编号 [1], [2]..."""

    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True,
        comment="报告中的引用编号 [1], [2]..."
    )
    task_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(
        sa.String(2048), nullable=False,
    )
    title: Mapped[str | None] = mapped_column(
        sa.String(500), default=None, server_default=sa.text("NULL"),
    )
    domain: Mapped[str | None] = mapped_column(
        sa.String(255), default=None, server_default=sa.text("NULL"),
    )
    fetched_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime,
        default=None,
        server_default=sa.text("NULL"),
    )
    fetch_status: Mapped[str | None] = mapped_column(
        sa.Enum(*FETCH_STATUS_ENUM, name="fetch_status"),
        default=None,
        server_default=sa.text("NULL"),
    )
    content: Mapped[str | None] = mapped_column(
        sa.Text,
        default=None,
        server_default=sa.text("NULL"),
        comment="网页 Markdown 正文；fetch_status='success' 时写入",
    )

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    # ── 索引 ──
    __table_args__ = (
        # uk_task_url：同任务内 URL 去重（对齐 DATABASE.md §2.4，url 取前缀 255 以满足索引长度限制）
        sa.Index(
            "uk_task_url", "task_id", "url", unique=True, mysql_length={"url": 255}
        ),
        sa.Index("idx_task", "task_id"),
    )

    # ── 关联 ──
    task = relationship("ResearchTask", back_populates="sources")
    evidence_items = relationship("EvidenceItem", back_populates="source", lazy="selectin")

    def __repr__(self):
        return f"<ResearchSource(id={self.id}, domain={self.domain!r})>"
