"""Material provenance, aliases, immutable knowledge revisions and import receipts."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0002"
down_revision = "20261013_0001"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("material_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_key", sa.String(200), nullable=False, unique=True),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("uri", sa.Text()), *timestamps())
    op.create_table("knowledge_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("knowledge_point_id", sa.Uuid(), sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False, unique=True), *timestamps())
    op.create_index("ix_knowledge_aliases_knowledge_point_id", "knowledge_aliases", ["knowledge_point_id"])
    op.create_table("knowledge_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("knowledge_point_id", sa.Uuid(), sa.ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("material_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("source_version", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False), sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("review_reasons", sa.JSON(), nullable=False), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), nullable=False), sa.Column("model_name", sa.String(200)),
        sa.Column("parser_version", sa.String(100), nullable=False), sa.Column("reviewer", sa.String(200)),
        sa.Column("review_note", sa.Text()), sa.Column("reviewed_at", sa.DateTime(timezone=True)), *timestamps(),
        sa.UniqueConstraint("knowledge_point_id", "version", name="uq_knowledge_revision_version"),
        sa.UniqueConstraint("knowledge_point_id", "source_id", "content_hash", name="uq_knowledge_revision_source_content"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name="review_status_values"))
    op.create_index("ix_knowledge_revisions_knowledge_point_id", "knowledge_revisions", ["knowledge_point_id"])
    op.create_index("ix_knowledge_revisions_review_status", "knowledge_revisions", ["review_status"])
    op.create_table("material_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("material_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_version", sa.String(100), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False), sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("format", sa.String(20), nullable=False), sa.Column("parsed", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False), *timestamps(),
        sa.UniqueConstraint("source_id", "source_version", "content_hash", "parser_version"))


def downgrade():
    for name in ("material_imports", "knowledge_revisions", "knowledge_aliases", "material_sources"):
        op.drop_table(name)
