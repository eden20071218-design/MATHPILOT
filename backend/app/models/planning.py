from uuid import UUID
from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin
from app.models.entities import UUIDPrimaryKey


class PlanningRun(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'planning_runs'
    __table_args__ = (UniqueConstraint('student_id', 'fingerprint', name='uq_planning_fingerprint'),)
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'))
    plan_id: Mapped[UUID] = mapped_column(ForeignKey('learning_plans.id', ondelete='CASCADE'))
    previous_run_id: Mapped[UUID | None] = mapped_column(ForeignKey('planning_runs.id', ondelete='SET NULL'), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
