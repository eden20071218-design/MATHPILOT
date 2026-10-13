from datetime import datetime
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin
from app.models.entities import UUIDPrimaryKey


class ReminderPreference(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'reminder_preferences'
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'), unique=True)
    settings: Mapped[dict] = mapped_column(JSON)


class PushSubscription(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'push_subscriptions'
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'), index=True)
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True)
    endpoint: Mapped[str] = mapped_column(Text)
    keys: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Reminder(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'reminders'
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey('learning_tasks.id', ondelete='CASCADE'), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default='pending')
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PushDelivery(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'push_deliveries'
    __table_args__ = (UniqueConstraint('reminder_id', 'subscription_id', name='uq_reminder_subscription'),)
    reminder_id: Mapped[UUID] = mapped_column(ForeignKey('reminders.id', ondelete='CASCADE'))
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey('push_subscriptions.id', ondelete='CASCADE'))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_token: Mapped[str] = mapped_column(String(100), unique=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    displayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_windows: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FeedbackEvent(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = 'feedback_events'
    __table_args__ = (UniqueConstraint('student_id', 'request_key', name='uq_feedback_request'),)
    student_id: Mapped[UUID] = mapped_column(ForeignKey('students.id', ondelete='CASCADE'))
    task_id: Mapped[UUID] = mapped_column(ForeignKey('learning_tasks.id', ondelete='CASCADE'))
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey('task_attempts.id', ondelete='CASCADE'))
    request_key: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    replan_status: Mapped[str] = mapped_column(String(30))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
