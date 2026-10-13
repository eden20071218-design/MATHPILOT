import enum
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ExamStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    completed = "completed"
    archived = "archived"


class PlanStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    superseded = "superseded"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    skipped = "skipped"
    cancelled = "cancelled"


class GoalStatus(str, enum.Enum):
    active = "active"
    achieved = "achieved"
    cancelled = "cancelled"


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    read = "read"
    cancelled = "cancelled"
    failed = "failed"


class UUIDPrimaryKey:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Student(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "students"
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    exams: Mapped[list["Exam"]] = relationship(back_populates="student", cascade="all, delete-orphan")
    knowledge_states: Mapped[list["StudentKnowledgeState"]] = relationship(back_populates="student", cascade="all, delete-orphan")
    goals: Mapped[list["LearningGoal"]] = relationship(back_populates="student", cascade="all, delete-orphan")
    plans: Mapped[list["LearningPlan"]] = relationship(back_populates="student", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="student", cascade="all, delete-orphan")


class Exam(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "exams"
    __table_args__ = (UniqueConstraint("student_id", "title", "version"),)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[ExamStatus] = mapped_column(Enum(ExamStatus), default=ExamStatus.draft)
    version: Mapped[int] = mapped_column(Integer, default=1)
    total_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    achieved_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    student: Mapped[Student] = relationship(back_populates="exams")
    exam_questions: Mapped[list["ExamQuestion"]] = relationship(back_populates="exam", cascade="all, delete-orphan")


class KnowledgePoint(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "knowledge_points"
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(String(100), default="mathematics")
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeDependency(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "knowledge_dependencies"
    __table_args__ = (
        UniqueConstraint("prerequisite_id", "dependent_id"),
        CheckConstraint("prerequisite_id <> dependent_id", name="no_self_dependency"),
    )
    prerequisite_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    dependent_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    strength: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=1)


class Question(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "questions"
    external_ref: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    stem: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=0.5)
    version: Mapped[int] = mapped_column(Integer, default=1)

    knowledge_links: Mapped[list["QuestionKnowledgePoint"]] = relationship(back_populates="question", cascade="all, delete-orphan")
    exam_links: Mapped[list["ExamQuestion"]] = relationship(back_populates="question")


class QuestionKnowledgePoint(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "question_knowledge_points"
    __table_args__ = (UniqueConstraint("question_id", "knowledge_point_id"),)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    knowledge_point_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=1)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[Question] = relationship(back_populates="knowledge_links")


class ExamQuestion(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "exam_questions"
    __table_args__ = (
        UniqueConstraint("exam_id", "question_id", name="uq_exam_question"),
        UniqueConstraint("exam_id", "position", name="uq_exam_position"),
    )
    exam_id: Mapped[UUID] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    student_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    exam: Mapped[Exam] = relationship(back_populates="exam_questions")
    question: Mapped[Question] = relationship(back_populates="exam_links")


class StudentKnowledgeState(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "student_knowledge_states"
    __table_args__ = (UniqueConstraint("student_id", "knowledge_point_id", "recorded_at"),)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    knowledge_point_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    mastery: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=0.5)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    source_type: Mapped[str] = mapped_column(String(50), default="assessment")
    source_id: Mapped[UUID | None] = mapped_column(nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    student: Mapped[Student] = relationship(back_populates="knowledge_states")


class LearningGoal(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "learning_goals"
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    target_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    target_date: Mapped[date] = mapped_column(Date)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[GoalStatus] = mapped_column(Enum(GoalStatus), default=GoalStatus.active)

    student: Mapped[Student] = relationship(back_populates="goals")
    plans: Mapped[list["LearningPlan"]] = relationship(back_populates="goal")


class LearningPlan(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "learning_plans"
    __table_args__ = (UniqueConstraint("student_id", "goal_id", "version"),)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[UUID] = mapped_column(ForeignKey("learning_goals.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[PlanStatus] = mapped_column(Enum(PlanStatus), default=PlanStatus.draft)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped[Student] = relationship(back_populates="plans")
    goal: Mapped[LearningGoal] = relationship(back_populates="plans")
    tasks: Mapped[list["LearningTask"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class LearningTask(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "learning_tasks"
    __table_args__ = (UniqueConstraint("plan_id", "sequence", "version"),)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True)
    knowledge_point_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped[LearningPlan] = relationship(back_populates="tasks")
    attempts: Mapped[list["TaskAttempt"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskAttempt(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "task_attempts"
    __table_args__ = (UniqueConstraint("task_id", "attempt_number"),)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("learning_tasks.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    task: Mapped[LearningTask] = relationship(back_populates="attempts")


class Notification(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "notifications"
    student_id: Mapped[UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("learning_tasks.id", ondelete="CASCADE"), nullable=True)
    deduplication_key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(30), default="in_app")
    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), default=NotificationStatus.pending)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    student: Mapped[Student] = relationship(back_populates="notifications")
