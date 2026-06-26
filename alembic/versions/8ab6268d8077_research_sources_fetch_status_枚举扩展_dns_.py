"""research_sources fetch_status 枚举扩展 dns_error

Revision ID: 8ab6268d8077
Revises: fd49212435a6
Create Date: 2026-06-26 21:43:32.092667

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ab6268d8077'
down_revision: Union[str, Sequence[str], None] = 'fd49212435a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 扩展 fetch_status ENUM，加入 dns_error（与 app/models/enums.py 对齐）
    op.alter_column(
        'research_sources',
        'fetch_status',
        existing_type=sa.Enum('success', 'timeout', 'blocked', 'empty', name='fetch_status'),
        type_=sa.Enum('success', 'timeout', 'blocked', 'empty', 'dns_error', name='fetch_status'),
        existing_nullable=True,
        existing_server_default=sa.text('NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 回滚：移除 dns_error
    op.alter_column(
        'research_sources',
        'fetch_status',
        existing_type=sa.Enum('success', 'timeout', 'blocked', 'empty', 'dns_error', name='fetch_status'),
        type_=sa.Enum('success', 'timeout', 'blocked', 'empty', name='fetch_status'),
        existing_nullable=True,
        existing_server_default=sa.text('NULL'),
    )
