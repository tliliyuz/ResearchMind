"""添加_research_tasks_completed_at_索引用于_TTL_清理

Revision ID: 11eb68567494
Revises: e6f62d0a9f56
Create Date: 2026-07-01 23:29:52.420424

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11eb68567494'
down_revision: Union[str, Sequence[str], None] = 'e6f62d0a9f56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 新增 completed_at 索引，加速 TTL 清理 WHERE completed_at < cutoff
    op.create_index(
        'idx_research_tasks_completed_at',
        'research_tasks',
        [sa.text('completed_at DESC')],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_research_tasks_completed_at', table_name='research_tasks')
