"""Student accounts, revocable browser sessions and idempotent exam entry."""
from alembic import op
import sqlalchemy as sa

revision='20261013_0006'
down_revision='20261013_0005'
branch_labels=None
depends_on=None


def base():
    return [sa.Column('id',sa.Uuid(),primary_key=True),
            sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
            sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False)]


def student():
    return sa.Column('student_id',sa.Uuid(),sa.ForeignKey('students.id',ondelete='CASCADE'),nullable=False)


def upgrade():
    op.create_table('student_accounts',*base(),student(),
        sa.Column('password_hash',sa.Text(),nullable=False),sa.Column('preferences',sa.JSON(),nullable=False),
        sa.Column('failed_logins',sa.Integer(),nullable=False),sa.Column('locked_until',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('student_id',name='uq_student_accounts_student_id'))
    op.create_table('login_sessions',*base(),student(),sa.Column('token_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_login_sessions_student_id','login_sessions',['student_id'])
    op.create_index('ix_login_sessions_expires_at','login_sessions',['expires_at'])
    op.create_table('exam_submissions',*base(),student(),
        sa.Column('exam_id',sa.Uuid(),sa.ForeignKey('exams.id',ondelete='CASCADE'),unique=True,nullable=False),
        sa.Column('request_key',sa.String(100),nullable=False),sa.Column('input_hash',sa.String(64),nullable=False),
        sa.UniqueConstraint('student_id','request_key',name='uq_student_exam_submission'))


def downgrade():
    for table in ['exam_submissions','login_sessions','student_accounts']:
        op.drop_table(table)
