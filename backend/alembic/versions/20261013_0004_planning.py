"""Versioned planning workflow snapshots."""
from alembic import op
import sqlalchemy as sa
revision = '20261013_0004'
down_revision = '20261013_0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('planning_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('student_id', sa.Uuid(), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', sa.Uuid(), sa.ForeignKey('learning_plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('previous_run_id', sa.Uuid(), sa.ForeignKey('planning_runs.id', ondelete='SET NULL')),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('student_id', 'fingerprint', name='uq_planning_fingerprint'))


def downgrade():
    op.drop_table('planning_runs')
