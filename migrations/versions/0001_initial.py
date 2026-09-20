"""Initial PostgreSQL schema.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("parse_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_source_documents_project_id", "source_documents", ["project_id"])
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("generation_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_table(
        "training_samples",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id"), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("validation_status", sa.String(32), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_training_samples_document_id", "training_samples", ["document_id"])
    op.create_index("ix_training_samples_chunk_id", "training_samples", ["chunk_id"])
    op.create_index(
        "ix_training_samples_export",
        "training_samples",
        ["project_id", "review_status", "validation_status", "is_deleted"],
    )
    op.create_index("ix_training_samples_dedupe", "training_samples", ["project_id", "content_hash"])
    op.create_table(
        "validation_issues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id"), nullable=False),
        sa.Column("rule", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_validation_issues_sample_id", "validation_issues", ["sample_id"])
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(32)),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_pipeline_runs_project_id", "pipeline_runs", ["project_id"])
    op.create_table(
        "export_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("file_type", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_export_records_project_id", "export_records", ["project_id"])


def downgrade() -> None:
    op.drop_table("export_records")
    op.drop_table("pipeline_runs")
    op.drop_table("validation_issues")
    op.drop_table("training_samples")
    op.drop_table("chunks")
    op.drop_table("source_documents")
    op.drop_table("projects")
