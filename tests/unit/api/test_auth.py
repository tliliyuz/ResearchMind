"""Auth API 接口测试 — 覆盖 app/api/auth.py 全部 5 个端点。

对齐 TESTING_STRATEGY.md §4.1（关键路径 100% 覆盖）：
- 正常流程 + 每个错误码独立用例
- API 层验证序列化/HTTP 状态码，Service 层已在 test_auth_service.py 覆盖业务逻辑
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, hash_token, create_refresh_token
from app.models.user import User
from app.models.refresh_token import RefreshToken
from datetime import datetime, timedelta, timezone


# ═══════════════════════════════════════════════════════════════
# POST /api/auth/register
# ═══════════════════════════════════════════════════════════════


class TestRegisterAPI:
    """POST /api/auth/register — 用户注册"""

    async def test_正常注册_返回201和用户信息(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/register", json={
            "username": "apiuser", "password": "pass123"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == "0"
        assert data["data"]["username"] == "apiuser"
        assert data["data"]["role"] == "user"

    async def test_用户名重复_返回409_E1001(self, async_client: AsyncClient):
        await async_client.post("/api/auth/register", json={
            "username": "dupuser", "password": "pass123"
        })
        response = await async_client.post("/api/auth/register", json={
            "username": "dupuser", "password": "another"
        })
        assert response.status_code == 409
        data = response.json()
        assert data["code"] == "E1001"

    async def test_密码少于6字符_返回422_E9003(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/register", json={
            "username": "testuser", "password": "12345"
        })
        assert response.status_code == 422
        assert response.json()["code"] == "E9003"

    async def test_用户名少于2字符_返回422_E9003(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/register", json={
            "username": "a", "password": "pass123"
        })
        assert response.status_code == 422

    async def test_纯数字用户名_返回422(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/register", json={
            "username": "12345", "password": "pass123"
        })
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════
# POST /api/auth/login
# ═══════════════════════════════════════════════════════════════


class TestLoginAPI:
    """POST /api/auth/login — 用户登录"""

    async def _setup_user(self, db_session, username="loginuser", password="loginpass", status="active"):
        user = User(
            username=username,
            password_hash=hash_password(password),
            status=status,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    @pytest.fixture(autouse=True)
    async def _seed(self, db_session):
        """每个测试自动预置用户"""
        await self._setup_user(db_session)

    async def test_正常登录_返回200和token对(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/login", json={
            "username": "loginuser", "password": "loginpass"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "0"
        # 强断言：JWT 应为 3 段点分隔的格式
        access_token = data["data"]["access_token"]
        assert len(access_token.split(".")) == 3
        refresh_token = data["data"]["refresh_token"]
        assert len(refresh_token.split(".")) == 3
        assert data["data"]["token_type"] == "bearer"
        # API.md §2 规定 access_token 15 分钟（900 秒）
        assert data["data"]["expires_in"] == 900

    async def test_密码错误_返回401_E1002(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/login", json={
            "username": "loginuser", "password": "wrongpass"
        })
        assert response.status_code == 401
        assert response.json()["code"] == "E1002"

    async def test_用户不存在_返回401_E1002(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/login", json={
            "username": "nouser", "password": "pass123456"
        })
        assert response.status_code == 401
        assert response.json()["code"] == "E1002"

    async def test_用户被禁用_返回401_E1010(self, async_client: AsyncClient, db_session):
        await self._setup_user(db_session, username="disabled", password="pass123", status="disabled")
        response = await async_client.post("/api/auth/login", json={
            "username": "disabled", "password": "pass123"
        })
        assert response.status_code == 401
        assert response.json()["code"] == "E1010"


# ═══════════════════════════════════════════════════════════════
# POST /api/auth/refresh
# ═══════════════════════════════════════════════════════════════


class TestRefreshAPI:
    """POST /api/auth/refresh — Token 刷新"""

    async def _setup_with_rt(self, db_session, username="refreshuser", status="active"):
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

    async def test_正常刷新_返回200和新token对(self, async_client: AsyncClient, db_session):
        _, rt_str, _ = await self._setup_with_rt(db_session)
        response = await async_client.post("/api/auth/refresh", json={
            "refresh_token": rt_str
        })
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "0"
        assert data["data"]["access_token"] != ""
        assert data["data"]["refresh_token"] != ""
        # 新旧 refresh_token 不同（Rotation）
        assert data["data"]["refresh_token"] != rt_str

    async def test_token无效_返回401_E1008(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/refresh", json={
            "refresh_token": "invalid.token.here"
        })
        assert response.status_code == 401
        assert response.json()["code"] == "E1008"

    async def test_已吊销token重用_泄露检测_返回401_E1009(self, async_client: AsyncClient, db_session):
        _, rt_str, _ = await self._setup_with_rt(db_session)
        # 第一次刷新 → 吊销
        await async_client.post("/api/auth/refresh", json={"refresh_token": rt_str})
        # 第二次用旧 token → 泄露检测
        response = await async_client.post("/api/auth/refresh", json={"refresh_token": rt_str})
        assert response.status_code == 401
        assert response.json()["code"] == "E1009"

    async def test_token过期_返回401_E1006(self, async_client: AsyncClient, db_session):
        user = User(username="expireduser", password_hash=hash_password("pass"))
        db_session.add(user)
        await db_session.flush()

        expired = create_refresh_token(user.id)
        rt = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(expired),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(rt)
        await db_session.flush()

        response = await async_client.post("/api/auth/refresh", json={
            "refresh_token": expired
        })
        assert response.status_code == 401
        assert response.json()["code"] == "E1006"

    async def test_刷新时用户被禁用_返回401_E1010(self, async_client: AsyncClient, db_session):
        user, rt_str, _ = await self._setup_with_rt(db_session, username="laterdisabled")
        user.status = "disabled"
        await db_session.flush()

        response = await async_client.post("/api/auth/refresh", json={
            "refresh_token": rt_str
        })
        assert response.status_code == 401
        assert response.json()["code"] == "E1010"


# ═══════════════════════════════════════════════════════════════
# POST /api/auth/logout
# ═══════════════════════════════════════════════════════════════


class TestLogoutAPI:
    """POST /api/auth/logout — 退出登录"""

    async def _setup(self, db_session):
        user = User(username="logoutapi", password_hash=hash_password("pass"))
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

    async def test_正常退出_返回200(self, async_client: AsyncClient, db_session, auth_headers):
        _, rt_str, rt = await self._setup(db_session)
        response = await async_client.post(
            "/api/auth/logout",
            json={"refresh_token": rt_str},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["code"] == "0"

        # 验证 token 已吊销
        await db_session.refresh(rt)
        assert rt.revoked_at is not None


# ═══════════════════════════════════════════════════════════════
# PUT /api/auth/password
# ═══════════════════════════════════════════════════════════════


class TestChangePasswordAPI:
    """PUT /api/auth/password — 修改密码"""

    async def _setup(self, db_session):
        user = User(
            username="pwdapi",
            password_hash=hash_password("oldpass123"),
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

    async def test_正常改密_返回200(self, async_client: AsyncClient, db_session, auth_headers):
        user, rt_str, rt = await self._setup(db_session)
        response = await async_client.put(
            "/api/auth/password",
            json={"old_password": "oldpass123", "new_password": "newpass456"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["code"] == "0"

        # 旧 token 被吊销
        await db_session.refresh(rt)
        assert rt.revoked_at is not None

    async def test_旧密码错误_返回401_E1002(self, async_client: AsyncClient, db_session, auth_headers):
        await self._setup(db_session)
        response = await async_client.put(
            "/api/auth/password",
            json={"old_password": "wrongold", "new_password": "newpass"},
            headers=auth_headers,
        )
        assert response.status_code == 401
        assert response.json()["code"] == "E1002"

    async def test_新密码与旧密码相同_返回400_E1011(self, async_client: AsyncClient, db_session, auth_headers):
        await self._setup(db_session)
        response = await async_client.put(
            "/api/auth/password",
            json={"old_password": "oldpass123", "new_password": "oldpass123"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "E1011"


# ═══════════════════════════════════════════════════════════════
# 异常处理器集成验证
# ═══════════════════════════════════════════════════════════════


class TestExceptionHandlers:
    """全局异常处理器 — 通过 API 端点间接验证"""

    async def test_请求体无法解析_返回422_E9003(self, async_client: AsyncClient):
        response = await async_client.post("/api/auth/login", content="not json", headers={
            "Content-Type": "application/json"
        })
        assert response.status_code == 422
        assert response.json()["code"] == "E9003"

    async def test_未认证访问受保护路由_返回401_E1004(self, async_client: AsyncClient):
        """AuthMiddleware 对非公开路由未携带 Bearer Token 返回 401 E1004。"""
        response = await async_client.get("/api/nonexistent")
        assert response.status_code == 401
        assert response.json()["code"] == "E1004"
