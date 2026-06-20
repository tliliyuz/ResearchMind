"""trace 列与 updated_at 列补充

Revision ID: a2b3c4d5e6f7
Revises: 7685a032ccd7
Create Date: 2026-06-21

变更：
- research_tasks: 新增 trace JSON 列（Pipeline 七阶段 Trace 数据）
- research_steps: 新增 updated_at DATETIME 列
- research_sources: 新增 updated_at DATETIME 列
- evidence_items: 新增 updated_at DATETIME 列
- report_sections: 新增 updated_at DATETIME 列

对齐 DATABASE.md §2 表结构。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: str = '7685a032ccd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # research_tasks: 新增 trace JSON 列
    op.add_column('research_tasks',
        sa.Column('trace', sa.JSON(), server_default=sa.text('NULL'), nullable=True,
                   comment='Pipeline 七阶段 Trace JSON（TraceRecorder.finish() 产出），对齐 DATABASE.md §2.2')
    )

    # research_steps: 新增 updated_at
    op.add_column('research_steps',
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )

    # research_sources: 新增 updated_at
    op.add_column('research_sources',
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )

    # evidence_items: 新增 updated_at
    op.add_column('evidence_items',
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )

    # report_sections: 新增 updated_at
    op.add_column('report_sections',
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False)
    )


def downgrade() -> None:
    op.drop_column('research_tasks', 'trace')
    op.drop_column('research_steps', 'updated_at')
    op.drop_column('research_sources', 'updated_at')
    op.drop_column('evidence_items', 'updated_at')
    op.drop_column('report_sections', 'updated_at')
