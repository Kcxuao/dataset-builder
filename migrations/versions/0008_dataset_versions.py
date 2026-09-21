"""Add immutable dataset release snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("statistics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_dataset_versions_project_name"),
    )
    op.create_index("ix_dataset_versions_project_id", "dataset_versions", ["project_id"])
    op.create_table(
        "dataset_version_samples",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("dataset_versions.id"), nullable=False),
        sa.Column("sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("version_id", "sample_id", name="uq_dataset_version_samples_version_sample"),
    )
    op.create_index("ix_dataset_version_samples_version_id", "dataset_version_samples", ["version_id"])
    op.create_index(
        "ix_dataset_version_samples_version_ordinal",
        "dataset_version_samples",
        ["version_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_version_samples_version_ordinal", table_name="dataset_version_samples")
    op.drop_index("ix_dataset_version_samples_version_id", table_name="dataset_version_samples")
    op.drop_table("dataset_version_samples")
    op.drop_index("ix_dataset_versions_project_id", table_name="dataset_versions")
    op.drop_table("dataset_versions")
