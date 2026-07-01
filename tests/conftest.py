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
from sqlalchemy import event
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
# Metrics Registry 清理（必须在导入 app.metrics 前设置）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_metrics_registry():
    """每个测试前将 Prometheus Registry 数值归零，避免跨测试状态污染。"""
    from app.metrics.registry import _reset_for_testing

    _reset_for_testing()
    yield


# ═══════════════════════════════════════════════════════════════
# MySQL 专有类型 → SQLite 兼容渲染（仅测试环境）
# ═══════════════════════════════════════════════════════════════

from sqlalchemy.dialects.mysql import MEDIUMTEXT  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy import BigInteger  # noqa: E402


# SQLite 不支持 MEDIUMTEXT，注册编译降级为 TEXT（仅影响测试 DB DDL，
# 不改动生产模型 — report_sections.content 在 MySQL 仍为 MEDIUMTEXT）
@compiles(MEDIUMTEXT)
def _compile_mediumtext_sqlite(element, compiler, **kw):  # noqa: D401
    return "TEXT"


# SQLite 的 AUTOINCREMENT 仅对 INTEGER PRIMARY KEY 生效；BIGINT 主键不会
# 自增（NOT NULL constraint failed）。注册 BigInteger→INTEGER（仅 sqlite 方言），
# 使主键自增在测试库可用。生产 MySQL 仍为 BIGINT。
@compiles(BigInteger, "sqlite")
def _compile_biginteger_sqlite(element, compiler, **kw):  # noqa: D401
    return "INTEGER"


def _dedupe_index_names(metadata) -> None:
    """SQLite 索引名全局唯一，按表名前缀重命名重复索引。

    DATABASE.md 在多表复用同名索引（如 idx_task），MySQL 表级作用域合法，
    但 SQLite 报 OperationalError: index already exists。此处仅修改测试用
    metadata 的索引名，不触碰生产模型。
    """
    seen: set[str] = set()
    for table in metadata.tables.values():
        for index in table.indexes:
            if index.name in seen:
                index.name = f"ix_{table.name}_{index.name}"
            seen.add(index.name)


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

    # SQLite 默认不启用外键约束，在引擎级别通过事件为每个连接启用
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    async with engine.begin() as conn:
        # 确保所有模型在导入链中已注册到 Base.metadata
        from app.models.user import User  # noqa: F401
        from app.models.refresh_token import RefreshToken  # noqa: F401
        from app.models.research_task import ResearchTask  # noqa: F401
        from app.models.research_step import ResearchStep  # noqa: F401
        from app.models.agent_memory_entry import AgentMemoryEntry  # noqa: F401
        from app.models.research_source import ResearchSource  # noqa: F401
        from app.models.evidence_item import EvidenceItem  # noqa: F401
        from app.models.report_section import ReportSection  # noqa: F401
        from app.models.section_evidence import SectionEvidence  # noqa: F401
        from app.core.database import Base

        # SQLite 索引名为全局命名空间（MySQL 为表级作用域），
        # DATABASE.md 在多表上复用 idx_task/idx_parent 等同名索引，
        # 此处为测试环境按表名前缀重命名以保证唯一性，不改动生产模型。
        _dedupe_index_names(Base.metadata)

        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    """测试数据库会话 —— 每个测试函数独立事务，结束时自动回滚。

    使用「单连接 + 单事务」模式：所有写操作进入同一事务，
    测试结束统一 rollback，确保测试间零状态泄漏，且 API 层与
    Service 层在同测试内共享同一事务（互相可见未提交数据）。

    用法：
        async def test_xxx(db_session: AsyncSession):
            db_session.add(User(...))
            await db_session.flush()
            # 测试结束后全部回滚
    """
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with session_factory() as session:
            yield session
        await trans.rollback()


# ═══════════════════════════════════════════════════════════════
# FastAPI 测试客户端（异步）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
async def async_client(db_session: AsyncSession):
    """FastAPI 异步测试客户端 —— 复用测试 `db_session` 的事务。

    - `get_db` 覆盖为返回同一 `db_session`（API 写入进入测试事务，
      与 Service 层共享、随测试回滚，避免跨请求不可见问题）。
    - `get_current_user` 覆盖为直接读取 request.state（由 AuthMiddleware
      注入），避免生产 `get_current_user` 经 `async_session_factory()`
      打开真实 MySQL 连接。

    用法：
        async def test_login(async_client):
            response = await async_client.post("/api/auth/login", json={...})
            assert response.status_code == 200
    """
    from fastapi import Request
    from app.main import app
    from app.dependencies import get_current_user, get_db

    async def override_get_db():
        # 复用测试会话 —— API 层的 commit 在测试中重定向为 flush，
        # 避免提交外层事务导致跨测试数据污染。
        original_commit = db_session.commit

        async def _commit_to_flush():
            await db_session.flush()

        db_session.commit = _commit_to_flush
        try:
            yield db_session
        finally:
            db_session.commit = original_commit

    async def override_get_current_user(request: Request) -> dict:
        return {
            "user_id": getattr(request.state, "user_id", None),
            "username": getattr(request.state, "username", None),
            "role": getattr(request.state, "role", None),
        }

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

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
def valid_refresh_token_str() -> str:
    """生成有效 refresh_token 字符串（测试专用密钥，7 天有效期）。"""
    from app.core.security import create_refresh_token
    return create_refresh_token(user_id=1)


@pytest.fixture
def auth_headers(valid_access_token: str) -> dict:
    """携带有效 access_token 的请求头。"""
    return {"Authorization": f"Bearer {valid_access_token}"}


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
