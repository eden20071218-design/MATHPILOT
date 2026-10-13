"""Durable reminders, push subscriptions, delivery receipts and feedback outbox."""
from alembic import op
import sqlalchemy as sa

revision='20261013_0005'
down_revision='20261013_0004'
branch_labels=None
depends_on=None


def base():
    return [sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False)]


def fk(name, target, nullable=False, unique=False):
    return sa.Column(name,sa.Uuid(),sa.ForeignKey(target,ondelete='CASCADE'),nullable=nullable,unique=unique)


def upgrade():
    # Old SQLite databases tolerated duplicate constraint names; PostgreSQL does not.
    bind = op.get_bind()
    names = {('exam_id', 'question_id'): 'uq_exam_question', ('exam_id', 'position'): 'uq_exam_position'}
    legacy = [c for c in sa.inspect(bind).get_unique_constraints('exam_questions')
              if tuple(c['column_names']) in names and c['name'] != names[tuple(c['column_names'])]]
    if legacy and bind.dialect.name == 'sqlite':
        table = sa.Table('exam_questions', sa.MetaData(), autoload_with=bind)
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint) and tuple(constraint.columns.keys()) in names:
                constraint.name = names[tuple(constraint.columns.keys())]
        with op.batch_alter_table('exam_questions', copy_from=table, recreate='always'):
            pass
    elif legacy:
        for constraint in legacy:
            op.drop_constraint(constraint['name'], 'exam_questions', type_='unique')
            op.create_unique_constraint(names[tuple(constraint['column_names'])], 'exam_questions', constraint['column_names'])
    op.create_table('reminder_preferences',*base(),fk('student_id','students.id',unique=True),sa.Column('settings',sa.JSON(),nullable=False))
    op.create_table('push_subscriptions',*base(),fk('student_id','students.id'),
        sa.Column('endpoint_hash',sa.String(64),unique=True,nullable=False),sa.Column('endpoint',sa.Text(),nullable=False),
        sa.Column('keys',sa.JSON(),nullable=False),sa.Column('active',sa.Boolean(),nullable=False))
    op.create_index('ix_push_subscriptions_student_id','push_subscriptions',['student_id'])
    op.create_table('reminders',*base(),fk('student_id','students.id'),fk('task_id','learning_tasks.id',nullable=True),
        sa.Column('dedup_key',sa.String(100),unique=True,nullable=False),sa.Column('kind',sa.String(30),nullable=False),
        sa.Column('due_at',sa.DateTime(timezone=True),nullable=False),sa.Column('available_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('lease_until',sa.DateTime(timezone=True)),sa.Column('last_error',sa.Text()))
    op.create_index('ix_reminders_student_id','reminders',['student_id'])
    op.create_index('ix_reminders_available_at','reminders',['available_at'])
    op.create_table('push_deliveries',*base(),fk('reminder_id','reminders.id'),fk('subscription_id','push_subscriptions.id'),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('last_error',sa.Text()),sa.Column('receipt_token',sa.String(100),unique=True,nullable=False),
        sa.Column('accepted_at',sa.DateTime(timezone=True)),sa.Column('displayed_at',sa.DateTime(timezone=True)),sa.Column('open_windows',sa.Integer()),
        sa.UniqueConstraint('reminder_id','subscription_id',name='uq_reminder_subscription'))
    op.create_table('feedback_events',*base(),fk('student_id','students.id'),fk('task_id','learning_tasks.id'),fk('attempt_id','task_attempts.id'),
        sa.Column('request_key',sa.String(100),nullable=False),sa.Column('input_hash',sa.String(64),nullable=False),
        sa.Column('result',sa.JSON(),nullable=False),sa.Column('replan_status',sa.String(30),nullable=False),
        sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('lease_until',sa.DateTime(timezone=True)),sa.Column('last_error',sa.Text()),
        sa.UniqueConstraint('student_id','request_key',name='uq_feedback_request'))


def downgrade():
    for table in ['feedback_events','push_deliveries','reminders','push_subscriptions','reminder_preferences']:
        op.drop_table(table)
