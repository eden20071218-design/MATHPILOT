from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.entities import UUIDPrimaryKey


class MaterialSource(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "material_sources"
    source_key: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeAlias(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "knowledge_aliases"
    __table_args__ = (UniqueConstraint("normalized_name"),)
    knowledge_point_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200))


class KnowledgeRevision(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("knowledge_point_id", "version", name="uq_knowledge_revision_version"),
        UniqueConstraint("knowledge_point_id", "source_id", "content_hash", name="uq_knowledge_revision_source_content"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name="review_status_values"),
    )
    knowledge_point_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("material_sources.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    source_version: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict] = mapped_column(JSON)
    original_text: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    review_reasons: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(100))
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MaterialImport(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "material_imports"
    __table_args__ = (UniqueConstraint("source_id", "source_version", "content_hash", "parser_version"),)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("material_sources.id", ondelete="RESTRICT"))
    source_version: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(100))
    original_text: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(20))
    parsed: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)

