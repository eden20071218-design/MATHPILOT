from datetime import datetime
from uuid import UUID
from sqlalchemy import ForeignKey, String, Text, JSON, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin
from app.models.entities import UUIDPrimaryKey


class StudentAccount(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'student_accounts'
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginSession(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'login_sessions'
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ExamSubmission(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'exam_submissions'
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'))
    exam_id: Mapped[UUID] = mapped_column(ForeignKey('exams.id', ondelete='CASCADE'), unique=True)
    request_key: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    from sqlalchemy import UniqueConstraint
    __table_args__ = (UniqueConstraint('student_id', 'request_key', name='uq_student_exam_submission'),)
