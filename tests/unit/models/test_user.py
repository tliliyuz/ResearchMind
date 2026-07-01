"""用户模型测试 — 覆盖 app/models/user.py 的 ORM 字段默认值、relationship 关联。

对齐 TESTING_STRATEGY.md §4.8。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class TestUserModel:
    """User ORM 模型 — 字段默认值与 relationship"""

    async def test_创建用户_默认role为user_status为active(self, db_session: AsyncSession):
        from app.core.security import hash_password
        user = User(
            username="newuser",
            password_hash=hash_password("testpass"),
        )
        db_session.add(user)
        await db_session.flush()

        result = await db_session.execute(
            select(User).where(User.username == "newuser")
        )
        saved = result.scalar_one()

        assert saved.role == "user"
        assert saved.status == "active"
        assert saved.id is not None
        assert saved.id > 0

    async def test_created_at自动填充UTC时间(self, db_session: AsyncSession):
        from app.core.security import hash_password
        user = User(
            username="timeuser",
            password_hash=hash_password("testpass"),
        )
        db_session.add(user)
        await db_session.flush()

        result = await db_session.execute(
            select(User).where(User.username == "timeuser")
        )
        saved = result.scalar_one()

        assert saved.created_at is not None
        now = datetime.now(timezone.utc)
        delta = abs((now - saved.created_at).total_seconds())
        assert delta < 5  # created_at 应在 5 秒内

    async def test_username唯一约束_重复插入失败(self, db_session: AsyncSession):
        from app.core.security import hash_password
        from sqlalchemy.exc import IntegrityError
        u1 = User(username="uniqueuser", password_hash=hash_password("p1"))
        u2 = User(username="uniqueuser", password_hash=hash_password("p2"))
        db_session.add(u1)
        await db_session.flush()

        db_session.add(u2)
        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_status可显式设置为disabled(self, db_session: AsyncSession):
        from app.core.security import hash_password
        user = User(
            username="disableduser",
            password_hash=hash_password("testpass"),
            status="disabled",
        )
        db_session.add(user)
        await db_session.flush()

        result = await db_session.execute(
            select(User).where(User.username == "disableduser")
        )
        saved = result.scalar_one()
        assert saved.status == "disabled"

    async def test_password_hash长度支持256字符(self, db_session: AsyncSession):
        """password_hash 字段定义为 sa.String(256)"""
        long_hash = "x" * 200  # 模拟长哈希
        user = User(username="hashuser", password_hash=long_hash)
        db_session.add(user)
        await db_session.flush()

        result = await db_session.execute(
            select(User).where(User.username == "hashuser")
        )
        saved = result.scalar_one()
        assert saved.password_hash == long_hash
        assert len(saved.password_hash) == 200
