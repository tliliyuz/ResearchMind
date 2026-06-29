"""添加 research_tasks 复合索引避免 filesort 1038

Revision ID: 4f784e6a8c49
Revises: 8ab6268d8077
Create Date: 2026-06-29 23:13:32.378655

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '4f784e6a8c49'
down_revision: Union[str, Sequence[str], None] = '8ab6268d8077'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    """检查索引是否存在，兼容 MySQL expression index 命名差异。"""
    conn = op.get_bind()
    inspector = inspect(conn)
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    """Upgrade schema."""
    # idx_score 表达式索引需要重建（MySQL 不支持 expression index 的降序，
    # 在此统一处理，与模型定义同步）
    if _index_exists("evidence_items", "idx_score"):
        op.drop_index("idx_score", table_name="evidence_items")
    op.create_index(
        "idx_score", "evidence_items",
        ["task_id", sa.text("relevance_score DESC")],
        unique=False,
    )

    # 先创建复合索引（覆盖 FK 对 user_id 索引的要求）
    if not _index_exists("research_tasks", "idx_user_created"):
        op.create_index(
            "idx_user_created", "research_tasks",
            ["user_id", sa.text("created_at DESC")],
            unique=False,
        )
    if not _index_exists("research_tasks", "idx_user_status_created"):
        op.create_index(
            "idx_user_status_created", "research_tasks",
            ["user_id", "status", sa.text("created_at DESC")],
            unique=False,
        )

    # 再删除旧单列索引（idx_user 可能被 FK 约束锁定，idx_created 可能不存在）
    # idx_user_created 以 user_id 开头，已满足 FK 索引需求，删 idx_user 无风险
    if _index_exists("research_tasks", "idx_user"):
        op.drop_index("idx_user", table_name="research_tasks")
    if _index_exists("research_tasks", "idx_created"):
        op.drop_index("idx_created", table_name="research_tasks")


def downgrade() -> None:
    """Downgrade schema."""
    # 恢复旧索引
    if _index_exists("research_tasks", "idx_user_status_created"):
        op.drop_index("idx_user_status_created", table_name="research_tasks")
    if _index_exists("research_tasks", "idx_user_created"):
        op.drop_index("idx_user_created", table_name="research_tasks")
    if not _index_exists("research_tasks", "idx_user"):
        op.create_index("idx_user", "research_tasks", ["user_id"], unique=False)
    if not _index_exists("research_tasks", "idx_created"):
        op.create_index(
            "idx_created", "research_tasks",
            [sa.text("created_at DESC")],
            unique=False,
        )

    # 恢复 evidence_items.idx_score
    if _index_exists("evidence_items", "idx_score"):
        op.drop_index("idx_score", table_name="evidence_items")
    op.create_index(
        "idx_score", "evidence_items",
        ["task_id", "relevance_score"],
        unique=False,
    )
