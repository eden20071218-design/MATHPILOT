"""Persist reproducible diagnosis reports and uncertainty."""
from alembic import op
import sqlalchemy as sa

revision = '20261013_0003'
down_revision = '20261013_0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('diagnosis_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('student_id', sa.Uuid(), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('exam_id', sa.Uuid(), sa.ForeignKey('exams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('model_version', sa.String(100), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False), sa.Column('report', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('student_id', 'input_hash', 'model_version', name='uq_diagnosis_input_model'))
    op.create_index('ix_diagnosis_runs_student_id', 'diagnosis_runs', ['student_id'])
    op.create_index('ix_diagnosis_runs_exam_id', 'diagnosis_runs', ['exam_id'])


def downgrade():
    op.drop_table('diagnosis_runs')
