"""
ORM 模型共享类型与工具函数。

- UTCDateTime：TypeDecorator，ORM 层确保读写均带 UTC tzinfo（对齐 docmind `models/_types.py`）
- utcnow()：返回当前 UTC aware datetime（供 Python 侧 default 使用，与 UTCDateTime 兼容）
- new_uuid()：生成 UUID4 字符串（CHAR(36) 格式）

集中定义避免在各模型文件中重复。时区方案对齐 docmind：
- MySQL DATETIME 列不存储时区，驱动返回 naive datetime
- UTCDateTime 在 ORM 层完成 aware ↔ naive 双向转换：
  - 写入：astimezone(UTC) + replace(tzinfo=None) → DB 存 UTC naive
  - 读取：replace(tzinfo=UTC) → 返回 aware datetime
- 连接级 `SET time_zone='+00:00'`（见 core/database.py）保证 CURRENT_TIMESTAMP 返回 UTC
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """UTC datetime 类型 — ORM 层确保始终返回 timezone-aware datetime。

    impl = DateTime 表示底层仍用 MySQL DATETIME 列存储，无需迁移。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        """写入 DB 前：转为 UTC 并剥离 tzinfo（DB 存 naive UTC 值）。"""
        if value is None:
            return None
        # aware → 转 UTC 再剥离；naive 视为已是 UTC 直接剥离
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        """从 DB 读取后：附加 UTC tzinfo（返回 aware datetime）。"""
        if value is None:
            return None
        # DB 约定存储 UTC → 直接附加 UTC tzinfo
        return value.replace(tzinfo=timezone.utc)


def utc_now():
    """返回当前 UTC 时间（aware，带 UTC tzinfo）。

    aware 返回值与 UTCDateTime 兼容：写入时由 process_bind_param 转为 naive UTC 存储。
    注意：函数名使用 utc_now()（含下划线），避免与 Python 3.12 弃用的 datetime.utcnow() 混淆。
    """
    return datetime.now(timezone.utc)


# 兼容别名：保留旧函数名 utcnow 以便渐进迁移，后续版本移除
utcnow = utc_now



def new_uuid():
    """生成 UUID4 字符串（CHAR(36) 格式）。"""
    return str(uuid.uuid4())
