"""添加 ResearchTask.updated_at 列

Revision ID: c02701951a41
Revises: a2b3c4d5e6f7
Create Date: 2026-06-25 14:30:43.575683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c02701951a41'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('research_tasks', sa.Column(
        'updated_at',
        sa.DateTime(timezone=True),
        server_default=sa.text('CURRENT_TIMESTAMP'),
        nullable=False,
        comment='记录最后修改时间（ORM onupdate 维护）',
    ))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('research_tasks', 'updated_at')
