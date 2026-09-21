"""Add resumable teacher-answer distillation jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "distillation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("pipeline_runs.id"), nullable=False),
        sa.Column("source_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id"), nullable=False),
        sa.Column("candidate_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_distillation_jobs_run_status", "distillation_jobs", ["run_id", "status"])
    op.create_index("ix_distillation_jobs_source", "distillation_jobs", ["source_sample_id"])


def downgrade() -> None:
    op.drop_index("ix_distillation_jobs_source", table_name="distillation_jobs")
    op.drop_index("ix_distillation_jobs_run_status", table_name="distillation_jobs")
    op.drop_table("distillation_jobs")
