"""全项目共享的 pytest fixtures — 测试 DB、HTTP 客户端、认证 token。

使用 SQLite 内存数据库（零外部依赖），每个测试函数独立事务隔离，
测试结束自动回滚，确保测试间无状态泄漏。

对齐 CLAUDE.md 测试约定：
  - 环境变量在导入 app 前设置，防止真实配置泄露到测试
  - 断言遵循强断言规则（验证具体值/错误码/顺序）
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ═══════════════════════════════════════════════════════════════
# 测试环境变量（在导入任何 app 模块前设置）
# ═══════════════════════════════════════════════════════════════

os.environ["ENV"] = "testing"
os.environ["DEBUG"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-only"
os.environ["REFRESH_TOKEN_SECRET_KEY"] = "test-refresh-secret-key-for-testing-only"
os.environ["LLM_API_KEY"] = "test-llm-api-key"
os.environ["RATE_LIMIT_ENABLED"] = "false"


# ═══════════════════════════════════════════════════════════════
# Event Loop
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def event_loop():
    """session 级事件循环（pytest-asyncio 要求）。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ═══════════════════════════════════════════════════════════════
# 测试数据库引擎与会话
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
async def test_engine():
    """创建测试专用 SQLite 内存引擎（session 级复用）。

    零外部依赖 —— 无需 MySQL/Redis，所有单元测试秒级完成。
    建表通过 `Base.metadata.create_all` 自动完成。

    注意：需确保所有 ORM 模型已被导入（通过 app.models.__init__），
    否则 Base.metadata 不包含对应表。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        # 确保所有模型在导入链中已注册到 Base.metadata
        from app.models.user import User  # noqa: F401
        from app.models.refresh_token import RefreshToken  # noqa: F401
        from app.models.research_task import ResearchTask  # noqa: F401
        from app.models.research_step import ResearchStep  # noqa: F401
        from app.models.research_source import ResearchSource  # noqa: F401
        from app.models.evidence_item import EvidenceItem  # noqa: F401
        from app.models.report_section import ReportSection  # noqa: F401
        from app.models.section_evidence import SectionEvidence  # noqa: F401
        from app.core.database import Base
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """测试数据库会话 —— 每个测试函数独立会话，结束时自动回滚。

    用法：
        async def test_xxx(db_session: AsyncSession):
            db_session.add(User(...))
            await db_session.flush()
            # 测试结束后全部回滚
    """
    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ═══════════════════════════════════════════════════════════════
# FastAPI 测试客户端（异步）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
async def async_client(test_engine):
    """FastAPI 异步测试客户端 —— 覆盖 `get_db` 依赖为测试 SQLite。

    所有 API 层测试通过此客户端发起 HTTP 请求，无需真实服务器。

    用法：
        async def test_login(async_client):
            response = await async_client.post("/api/auth/login", json={...})
            assert response.status_code == 200
    """
    from app.main import app
    from app.dependencies import get_db

    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
# 认证 Token Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def valid_access_token() -> str:
    """生成有效 access_token（测试专用密钥，15min 有效期）。"""
    from app.core.security import create_access_token
    return create_access_token(user_id=1, username="testuser", role="user")


@pytest.fixture
def valid_admin_token() -> str:
    """生成 admin 角色的有效 access_token。"""
    from app.core.security import create_access_token
    return create_access_token(user_id=2, username="admin", role="admin")


@pytest.fixture
def valid_refresh_token_str() -> str:
    """生成有效 refresh_token 字符串（测试专用密钥，7 天有效期）。"""
    from app.core.security import create_refresh_token
    return create_refresh_token(user_id=1)


@pytest.fixture
def auth_headers(valid_access_token: str) -> dict:
    """携带有效 access_token 的请求头。"""
    return {"Authorization": f"Bearer {valid_access_token}"}


@pytest.fixture
def admin_headers(valid_admin_token: str) -> dict:
    """携带 admin access_token 的请求头。"""
    return {"Authorization": f"Bearer {valid_admin_token}"}


# ═══════════════════════════════════════════════════════════════
# 预置数据 Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
async def seeded_user(db_session: AsyncSession) -> tuple:
    """预置：1 个活跃普通用户 + 1 个有效 refresh_token。

    Returns:
        (User, refresh_token_str): 预置的用户 ORM 对象和 refresh_token 明文
    """
    from app.models.user import User
    from app.models.refresh_token import RefreshToken
    from app.core.security import hash_password, hash_token, create_refresh_token

    user = User(
        id=1,
        username="testuser",
        password_hash=hash_password("testpass123"),
        role="user",
        status="active",
    )
    db_session.add(user)
    await db_session.flush()

    token_str = create_refresh_token(user_id=1)
    rt = RefreshToken(
        user_id=1,
        token_hash=hash_token(token_str),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(rt)
    await db_session.flush()

    return user, token_str
