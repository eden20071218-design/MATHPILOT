"""Initial MathPilot schema."""

from alembic import op

from app.db.base import Base
import app.models  # noqa: F401

revision = "20261013_0001"
down_revision = None
branch_labels = None
depends_on = None

# Freeze the phase-one table set: later model additions belong to later migrations.
TABLE_NAMES = {
    "students", "exams", "exam_questions", "knowledge_points", "knowledge_dependencies",
    "questions", "question_knowledge_points", "student_knowledge_states", "learning_goals",
    "learning_plans", "learning_tasks", "task_attempts", "notifications",
}


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=[Base.metadata.tables[name] for name in TABLE_NAMES])


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=[Base.metadata.tables[name] for name in TABLE_NAMES])
