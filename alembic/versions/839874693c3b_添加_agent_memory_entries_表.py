"""添加 agent_memory_entries 表

Revision ID: 839874693c3b
Revises: 4f784e6a8c49
Create Date: 2026-06-29 23:54:32.923168

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.models  # noqa: F401 — 触发模型注册，使 UTCDateTime 可被引用
from app.models._types import UTCDateTime


# revision identifiers, used by Alembic.
revision: str = '839874693c3b'
down_revision: Union[str, Sequence[str], None] = '4f784e6a8c49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 agent_memory_entries 表及索引。"""
    op.create_table('agent_memory_entries',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('step_id', sa.String(length=36), server_default=sa.text('NULL'), nullable=True, comment='关联 ResearchStep.id'),
    sa.Column('iteration', sa.Integer(), nullable=False, comment='Agent Loop 轮次'),
    sa.Column('phase', sa.String(length=50), nullable=False, comment='所属 phase'),
    sa.Column('entry_type', sa.Enum('thought', 'action', 'observation', 'finish', name='agent_memory_entry_type'), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False, comment='ReActEntry 完整字段'),
    sa.Column('created_at', UTCDateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['step_id'], ['research_steps.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['research_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_agent_memory_task', 'agent_memory_entries', ['task_id'], unique=False)
    op.create_index('idx_agent_memory_task_created', 'agent_memory_entries', ['task_id', sa.text('created_at DESC')], unique=False)
    op.create_index('idx_agent_memory_task_iteration', 'agent_memory_entries', ['task_id', 'iteration'], unique=False)


def downgrade() -> None:
    """移除 agent_memory_entries 表及索引。"""
    op.drop_index('idx_agent_memory_task_iteration', table_name='agent_memory_entries')
    op.drop_index('idx_agent_memory_task_created', table_name='agent_memory_entries')
    op.drop_index('idx_agent_memory_task', table_name='agent_memory_entries')
    op.drop_table('agent_memory_entries')
