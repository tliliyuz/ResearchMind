"""
用户表 ORM 模型 —— users 表。

表结构严格遵循 [DATABASE.md §2](docs/DATABASE.md#2-表结构)。
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models._types import UTCDateTime


class User(Base):
    """用户表 —— 认证、角色、状态。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(
        sa.String(64), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        sa.String(256), nullable=False, comment="bcrypt 哈希"
    )
    role: Mapped[str] = mapped_column(
        sa.Enum("user", "admin", name="user_role"),
        default="user",
        server_default=sa.text("'user'"),
    )
    status: Mapped[str] = mapped_column(
        sa.Enum("active", "disabled", name="user_status"),
        default="active",
        server_default=sa.text("'active'"),
        comment="disabled 后拒绝登录与 Token 刷新",
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # ── 关联 ──
    refresh_tokens = relationship("RefreshToken", back_populates="user", lazy="noload")
    research_tasks = relationship("ResearchTask", back_populates="user", lazy="noload")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username!r}, role={self.role})>"
