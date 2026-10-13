from uuid import UUID
from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin
from app.models.entities import UUIDPrimaryKey


class DiagnosisRun(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'diagnosis_runs'
    __table_args__ = (UniqueConstraint('student_id', 'input_hash', 'model_version', name='uq_diagnosis_input_model'),)
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'), index=True)
    exam_id: Mapped[UUID] = mapped_column(ForeignKey('exams.id', ondelete='CASCADE'), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(100))
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)
