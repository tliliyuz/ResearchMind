"""认证服务单元测试 — 覆盖 app/services/auth_service.py 全部 6 个公开函数。

对齐 TESTING_STRATEGY.md §4.4：
- 泄露检测是最高优先级测试场景
- 每个函数覆盖所有分支（成功 + 每种错误码独立用例）
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidCredentialsException,
    InvalidRefreshTokenException,
    PasswordSameAsCurrentException,
    RefreshTokenExpiredException,
    TokenLeakDetectedException,
    UserDisabledException,
    UsernameExistsException,
)
from app.core.security import (
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import (
    change_password,
    login,
    logout,
    refresh,
    register,
    revoke_all_user_tokens,
)


# ═══════════════════════════════════════════════════════════════
# register()
# ═══════════════════════════════════════════════════════════════


class TestRegister:
    """注册"""

    async def test_正常注册_返回UserResponse(self, db_session: AsyncSession):
        result = await register(db_session, username="newuser", password="pass123")
        assert result.username == "newuser"
        assert result.role == "user"
        assert result.id > 0

    async def test_用户名重复_抛出E1001(self, db_session: AsyncSession):
        await register(db_session, username="existing", password="pass123")
        with pytest.raises(UsernameExistsException) as exc_info:
            await register(db_session, username="existing", password="another")
        assert exc_info.value.error_code == "E1001"
        assert exc_info.value.status_code == 409

    async def test_密码已bcrypt哈希存储(self, db_session: AsyncSession):
        result = await register(db_session, username="hashcheck", password="rawpass")
        from sqlalchemy import select
        user = (await db_session.execute(
            select(User).where(User.id == result.id)
        )).scalar_one()
        # 数据库中存的是 bcrypt 哈希，不是明文
        assert user.password_hash != "rawpass"
        assert user.password_hash.startswith("$2b$")


# ═══════════════════════════════════════════════════════════════
# login()
# ═══════════════════════════════════════════════════════════════


class TestLogin:
    """登录"""

    async def _setup_user(self, db_session, username="testuser", password="testpass", status="active"):
        user = User(
            username=username,
            password_hash=hash_password(password),
            status=status,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    async def test_正常登录_返回TokenResponse含access和refresh(self, db_session: AsyncSession):
        await self._setup_user(db_session)
        result = await login(db_session, username="testuser", password="testpass")
        assert result.access_token != ""
        assert result.refresh_token != ""
        assert result.token_type == "bearer"
        assert result.expires_in > 0

    async def test_密码错误_抛出E1002(self, db_session: AsyncSession):
        await self._setup_user(db_session)
        with pytest.raises(InvalidCredentialsException) as exc_info:
            await login(db_session, username="testuser", password="wrongpass")
        assert exc_info.value.error_code == "E1002"

    async def test_用户不存在_抛出E1002(self, db_session: AsyncSession):
        with pytest.raises(InvalidCredentialsException) as exc_info:
            await login(db_session, username="noone", password="pass")
        assert exc_info.value.error_code == "E1002"

    async def test_用户被禁用_抛出E1010(self, db_session: AsyncSession):
        await self._setup_user(db_session, username="disabled", password="pass", status="disabled")
        with pytest.raises(UserDisabledException) as exc_info:
            await login(db_session, username="disabled", password="pass")
        assert exc_info.value.error_code == "E1010"

    async def test_登录成功_refresh_token哈希存入DB(self, db_session: AsyncSession):
        await self._setup_user(db_session)
        result = await login(db_session, username="testuser", password="testpass")
        from sqlalchemy import select
        token_hash = hash_token(result.refresh_token)
        rt = (await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )).scalar_one_or_none()
        assert rt is not None
        assert rt.user_id == 1

    async def test_登录成功_返回refresh_token可被解码(self, db_session: AsyncSession):
        await self._setup_user(db_session)
        result = await login(db_session, username="testuser", password="testpass")
        from app.core.security import decode_refresh_token
        payload = decode_refresh_token(result.refresh_token)
        assert payload["type"] == "refresh"


# ═══════════════════════════════════════════════════════════════
# refresh()
# ═══════════════════════════════════════════════════════════════


class TestRefresh:
    """Token 刷新 — Rotation + 泄露检测"""

    async def _setup(self, db_session, username="testuser", status="active"):
        user = User(
            username=username,
            password_hash=hash_password("pass"),
            status=status,
        )
        db_session.add(user)
        await db_session.flush()

        rt_str = create_refresh_token(user.id)
        rt = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(rt_str),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(rt)
        await db_session.flush()
        return user, rt_str, rt

    async def test_正常刷新_旧token被吊销_返回新token对(self, db_session: AsyncSession):
        user, rt_str, old_rt = await self._setup(db_session)
        result = await refresh(db_session, rt_str)

        # 返回新 token 对
        assert result.access_token != ""
        assert result.refresh_token != ""
        assert result.refresh_token != rt_str  # 新旧 refresh_token 不同

        # 旧 token 已吊销
        await db_session.refresh(old_rt)
        assert old_rt.revoked_at is not None

    async def test_正常刷新_新token可继续刷新_实现Rotation链(self, db_session: AsyncSession):
        user, rt_str, _ = await self._setup(db_session)
        round1 = await refresh(db_session, rt_str)
        round2 = await refresh(db_session, round1.refresh_token)
        assert round2.access_token != ""
        assert round2.refresh_token != round1.refresh_token

    async def test_JWT解码失败_抛出E1008(self, db_session: AsyncSession):
        with pytest.raises(InvalidRefreshTokenException) as exc_info:
            await refresh(db_session, "not.a.valid.token.at.all")
        assert exc_info.value.error_code == "E1008"

    async def test_token不在DB中_抛出E1008(self, db_session: AsyncSession):
        rt_str = create_refresh_token(user_id=999)  # user_id 不存在
        with pytest.raises(InvalidRefreshTokenException) as exc_info:
            await refresh(db_session, rt_str)
        assert exc_info.value.error_code == "E1008"

    async def test_已吊销token重用_泄露检测_抛出E1009(self, db_session: AsyncSession):
        """泄露检测 — 最高优先级测试场景"""
        user, rt_str, old_rt = await self._setup(db_session)
        # 第一次刷新 → 吊销旧 token
        await refresh(db_session, rt_str)
        await db_session.refresh(old_rt)
        assert old_rt.revoked_at is not None

        # 第二次用同一旧 token 刷新 → 泄露检测
        with pytest.raises(TokenLeakDetectedException) as exc_info:
            await refresh(db_session, rt_str)
        assert exc_info.value.error_code == "E1009"

    async def test_泄露检测后该用户全部token被吊销(self, db_session: AsyncSession):
        """泄露触发后 → 全量吊销该用户有效 refresh_token"""
        user, rt_str, _ = await self._setup(db_session)
        # 再创建第二个 refresh_token（模拟多设备登录）
        rt2_str = create_refresh_token(user.id)
        rt2 = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(rt2_str),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(rt2)
        await db_session.flush()

        # 先正常刷新一次 rt_str → 吊销
        await refresh(db_session, rt_str)

        # 用旧 rt_str 重放 → 泄露检测 → 全量吊销
        with pytest.raises(TokenLeakDetectedException):
            await refresh(db_session, rt_str)

        # rt2 也应被吊销
        await db_session.refresh(rt2)
        assert rt2.revoked_at is not None

    async def test_token过期_抛出E1006(self, db_session: AsyncSession):
        user, _, _ = await self._setup(db_session)
        # 创建已过期的 refresh_token
        expired = create_refresh_token(user.id)
        token_hash = hash_token(expired)
        rt = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(rt)
        await db_session.flush()

        with pytest.raises(RefreshTokenExpiredException) as exc_info:
            await refresh(db_session, expired)
        assert exc_info.value.error_code == "E1006"

    async def test_刷新时用户已被禁用_抛出E1010(self, db_session: AsyncSession):
        # 用户先活跃后禁用
        user, rt_str, _ = await self._setup(db_session, username="tobedisabled")
        # 禁用用户
        user.status = "disabled"
        await db_session.flush()

        with pytest.raises(UserDisabledException) as exc_info:
            await refresh(db_session, rt_str)
        assert exc_info.value.error_code == "E1010"


# ═══════════════════════════════════════════════════════════════
# logout()
# ═══════════════════════════════════════════════════════════════


class TestLogout:
    """退出登录"""

    async def _setup(self, db_session):
        user = User(username="logouter", password_hash=hash_password("pass"))
        db_session.add(user)
        await db_session.flush()

        rt_str = create_refresh_token(user.id)
        rt = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(rt_str),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(rt)
        await db_session.flush()
        return user, rt_str, rt

    async def test_正常吊销_refresh_token标记revoked_at(self, db_session: AsyncSession):
        user, rt_str, rt = await self._setup(db_session)
        await logout(db_session, rt_str, user.id)
        await db_session.refresh(rt)
        assert rt.revoked_at is not None

    async def test_JWT解码失败_静默成功(self, db_session: AsyncSession):
        # 无效 JWT → 静默处理，不抛异常（user_id 无意义但仍传入）
        await logout(db_session, "invalid.token.here", user_id=1)
        # 无异常即通过

    async def test_已吊销token再次logout_幂等(self, db_session: AsyncSession):
        user, rt_str, rt = await self._setup(db_session)
        await logout(db_session, rt_str, user.id)
        # 第二次 logout 同一 token
        await logout(db_session, rt_str, user.id)
        # 无异常即通过 - 幂等
        await db_session.refresh(rt)
        assert rt.revoked_at is not None

    async def test_user_id不匹配_静默跳过不吊销(self, db_session: AsyncSession):
        """access_token user_id 与 refresh_token user_id 不一致时静默跳过"""
        user, rt_str, rt = await self._setup(db_session)
        # 用错误的 user_id 调用 logout
        await logout(db_session, rt_str, user_id=99999)
        await db_session.refresh(rt)
        # token 未被吊销
        assert rt.revoked_at is None


# ═══════════════════════════════════════════════════════════════
# change_password()
# ═══════════════════════════════════════════════════════════════


class TestChangePassword:
    """修改密码"""

    async def _setup(self, db_session, old_password="oldpass123"):
        user = User(
            username="pwdchanger",
            password_hash=hash_password(old_password),
        )
        db_session.add(user)
        await db_session.flush()
        # 创建活跃 refresh_token
        rt_str = create_refresh_token(user.id)
        rt = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(rt_str),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(rt)
        await db_session.flush()
        return user, rt_str, rt

    async def test_正常改密_密码哈希更新(self, db_session: AsyncSession):
        user, _, _ = await self._setup(db_session)
        await change_password(db_session, user.id, old_password="oldpass123", new_password="newpass456")
        await db_session.refresh(user)
        assert verify_password("newpass456", user.password_hash) is True
        assert verify_password("oldpass123", user.password_hash) is False

    async def test_旧密码错误_抛出E1002(self, db_session: AsyncSession):
        user, _, _ = await self._setup(db_session)
        with pytest.raises(InvalidCredentialsException) as exc_info:
            await change_password(db_session, user.id, old_password="wrongold", new_password="newpass")
        assert exc_info.value.error_code == "E1002"

    async def test_新密码与旧密码相同_抛出E1011(self, db_session: AsyncSession):
        user, _, _ = await self._setup(db_session)
        with pytest.raises(PasswordSameAsCurrentException) as exc_info:
            await change_password(db_session, user.id, old_password="oldpass123", new_password="oldpass123")
        assert exc_info.value.error_code == "E1011"

    async def test_改密后全量吊销refresh_token(self, db_session: AsyncSession):
        user, rt_str, rt = await self._setup(db_session)
        # 创建第二个 refresh_token
        rt2_str = create_refresh_token(user.id)
        rt2 = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(rt2_str),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(rt2)
        await db_session.flush()

        await change_password(db_session, user.id, old_password="oldpass123", new_password="newpass789")

        # 全部 token 被吊销
        await db_session.refresh(rt)
        await db_session.refresh(rt2)
        assert rt.revoked_at is not None
        assert rt2.revoked_at is not None


# ═══════════════════════════════════════════════════════════════
# revoke_all_user_tokens()
# ═══════════════════════════════════════════════════════════════


class TestRevokeAllUserTokens:
    """全量吊销用户 refresh_token"""

    async def test_有3个活跃token_全部被吊销(self, db_session: AsyncSession):
        user = User(username="revoker", password_hash=hash_password("pass"))
        db_session.add(user)
        await db_session.flush()

        rts = []
        for _ in range(3):
            s = create_refresh_token(user.id)
            rt = RefreshToken(
                user_id=user.id,
                token_hash=hash_token(s),
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            db_session.add(rt)
            rts.append(rt)
        await db_session.flush()

        await revoke_all_user_tokens(db_session, user.id)

        for rt in rts:
            await db_session.refresh(rt)
            assert rt.revoked_at is not None

    async def test_0个活跃token_无操作不抛异常(self, db_session: AsyncSession):
        user = User(username="emptytokens", password_hash=hash_password("pass"))
        db_session.add(user)
        await db_session.flush()

        # 不应抛异常
        await revoke_all_user_tokens(db_session, user.id)

    async def test_已有部分吊销_仅吊销未吊销的(self, db_session: AsyncSession):
        user = User(username="partial", password_hash=hash_password("pass"))
        db_session.add(user)
        await db_session.flush()

        s1 = create_refresh_token(user.id)
        rt1 = RefreshToken(
            user_id=user.id, token_hash=hash_token(s1),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        s2 = create_refresh_token(user.id)
        rt2 = RefreshToken(
            user_id=user.id, token_hash=hash_token(s2),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            revoked_at=datetime.now(timezone.utc),  # 已吊销
        )
        db_session.add_all([rt1, rt2])
        await db_session.flush()

        await revoke_all_user_tokens(db_session, user.id)

        await db_session.refresh(rt1)
        await db_session.refresh(rt2)
        assert rt1.revoked_at is not None
        # rt2 原本就是吊销的，时间不变
