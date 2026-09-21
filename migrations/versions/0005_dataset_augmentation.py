"""Persist augmentation lineage and resumable jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_samples", sa.Column("parent_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id")))
    op.add_column("training_samples", sa.Column("generation_run_id", sa.Uuid(), sa.ForeignKey("pipeline_runs.id")))
    op.create_index("ix_training_samples_parent", "training_samples", ["parent_sample_id"])
    op.create_index("ix_training_samples_generation_run", "training_samples", ["generation_run_id"])
    op.create_table(
        "augmentation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("pipeline_runs.id"), nullable=False),
        sa.Column("seed_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id"), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_augmentation_jobs_run_status", "augmentation_jobs", ["run_id", "status"])
    op.create_index("ix_augmentation_jobs_seed", "augmentation_jobs", ["seed_sample_id"])


def downgrade() -> None:
    op.drop_index("ix_augmentation_jobs_seed", table_name="augmentation_jobs")
    op.drop_index("ix_augmentation_jobs_run_status", table_name="augmentation_jobs")
    op.drop_table("augmentation_jobs")
    op.drop_index("ix_training_samples_generation_run", table_name="training_samples")
    op.drop_index("ix_training_samples_parent", table_name="training_samples")
    op.drop_column("training_samples", "generation_run_id")
    op.drop_column("training_samples", "parent_sample_id")
