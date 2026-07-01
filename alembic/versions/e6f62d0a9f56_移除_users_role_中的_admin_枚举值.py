"""移除 users.role 中的 admin 枚举值

Revision ID: e6f62d0a9f56
Revises: 839874693c3b
Create Date: 2026-07-01 22:10:26.449279

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f62d0a9f56'
down_revision: Union[str, Sequence[str], None] = '839874693c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # v1.0 取消 admin 角色：先将所有 admin 角色回退为 user，再收缩枚举范围
    op.execute("UPDATE users SET role = 'user' WHERE role = 'admin'")
    op.execute(
        "ALTER TABLE users MODIFY COLUMN role ENUM('user') "
        "NOT NULL DEFAULT 'user'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE users MODIFY COLUMN role ENUM('user', 'admin') "
        "NOT NULL DEFAULT 'user'"
    )
