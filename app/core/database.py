"""
数据库核心模块 —— SQLAlchemy async engine + session + Base。

- engine：全局异步引擎，MySQL time_zone='+00:00' 四层 UTC 统一
- async_session_factory：异步会话工厂，expire_on_commit=False
- Base：ORM 模型基类，所有模型通过 app.models 导入后注册

禁止在各模块中自行创建 engine/session —— 统一通过本模块获取。
FastAPI 依赖注入 `get_db()` 定义在 `app.dependencies`。
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ── 异步引擎 ─────────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,                    # DEBUG 时输出 SQL
    pool_size=20,                           # 连接池大小
    max_overflow=10,                        # 最大溢出连接数
    pool_pre_ping=True,                     # 连接前 ping 检测有效性
    pool_recycle=3600,                      # 1 小时回收连接
)

# ── 异步会话工厂 ─────────────────────────────────────────────

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,                 # commit 后不使实例过期
)


# ── 数据库时间修正器 ─────────────────────────────────────────
# MySQL 5.7 的 CURRENT_TIMESTAMP 可能不带时区，
# 通过此 hook 为读取到的 datetime 附加 UTC tzinfo。


@event.listens_for(engine.sync_engine, "connect")
def _set_timezone(dbapi_connection, connection_record):
    """连接建立后设置 time_zone 并注册 datetime 类型修正。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("SET time_zone = '+00:00'")
    cursor.close()


# ── Declarative Base ─────────────────────────────────────────


class Base(DeclarativeBase):
    """
    SQLAlchemy ORM 基类。

    所有模型类继承自此 Base，并通过 `app.models.__init__` 导入
    以使 Alembic 的 target_metadata 能够发现全部表。
    """
