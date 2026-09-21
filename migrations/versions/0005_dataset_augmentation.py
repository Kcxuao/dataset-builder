"""Persist augmentation lineage and resumable jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    """Return the columns currently present, including after a partial SQLite DDL run."""
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    """Return the indexes currently present, including after a partial SQLite DDL run."""
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _has_foreign_key(
    table_name: str,
    constrained_columns: list[str],
    referred_table: str,
    referred_columns: list[str],
) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(
        foreign_key["constrained_columns"] == constrained_columns
        and foreign_key["referred_table"] == referred_table
        and foreign_key["referred_columns"] == referred_columns
        for foreign_key in inspector.get_foreign_keys(table_name)
    )


def upgrade() -> None:
    # SQLite auto-commits most ALTER TABLE operations.  If a later operation in
    # this migration fails, Alembic does not advance its revision but columns
    # already added remain.  Probe the schema so rerunning 0005 resumes safely.
    training_sample_columns = _column_names("training_samples")
    missing_parent_id = "parent_sample_id" not in training_sample_columns
    missing_generation_run_id = "generation_run_id" not in training_sample_columns
    parent_foreign_key_exists = _has_foreign_key(
        "training_samples", ["parent_sample_id"], "training_samples", ["id"]
    )
    generation_run_foreign_key_exists = _has_foreign_key(
        "training_samples", ["generation_run_id"], "pipeline_runs", ["id"]
    )

    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot ALTER TABLE to add a foreign-key constraint. Batch mode
        # copies existing rows into a reconstructed table and preserves a partial
        # previous attempt (for example, parent_sample_id without its FK).
        if (
            missing_parent_id
            or missing_generation_run_id
            or not parent_foreign_key_exists
            or not generation_run_foreign_key_exists
        ):
            with op.batch_alter_table("training_samples", recreate="always") as batch:
                if missing_parent_id:
                    batch.add_column(sa.Column("parent_sample_id", sa.Uuid()))
                if missing_generation_run_id:
                    batch.add_column(sa.Column("generation_run_id", sa.Uuid()))
                if not parent_foreign_key_exists:
                    batch.create_foreign_key(
                        "fk_training_samples_parent_sample_id",
                        "training_samples",
                        ["parent_sample_id"],
                        ["id"],
                    )
                if not generation_run_foreign_key_exists:
                    batch.create_foreign_key(
                        "fk_training_samples_generation_run_id",
                        "pipeline_runs",
                        ["generation_run_id"],
                        ["id"],
                    )
    else:
        if missing_parent_id:
            op.add_column(
                "training_samples",
                sa.Column("parent_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id")),
            )
        if missing_generation_run_id:
            op.add_column(
                "training_samples",
                sa.Column("generation_run_id", sa.Uuid(), sa.ForeignKey("pipeline_runs.id")),
            )

    training_sample_indexes = _index_names("training_samples")
    if "ix_training_samples_parent" not in training_sample_indexes:
        op.create_index("ix_training_samples_parent", "training_samples", ["parent_sample_id"])
    if "ix_training_samples_generation_run" not in training_sample_indexes:
        op.create_index("ix_training_samples_generation_run", "training_samples", ["generation_run_id"])

    inspector = sa.inspect(op.get_bind())
    if "augmentation_jobs" not in inspector.get_table_names():
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

    augmentation_job_indexes = _index_names("augmentation_jobs")
    if "ix_augmentation_jobs_run_status" not in augmentation_job_indexes:
        op.create_index("ix_augmentation_jobs_run_status", "augmentation_jobs", ["run_id", "status"])
    if "ix_augmentation_jobs_seed" not in augmentation_job_indexes:
        op.create_index("ix_augmentation_jobs_seed", "augmentation_jobs", ["seed_sample_id"])


def downgrade() -> None:
    op.drop_index("ix_augmentation_jobs_seed", table_name="augmentation_jobs")
    op.drop_index("ix_augmentation_jobs_run_status", table_name="augmentation_jobs")
    op.drop_table("augmentation_jobs")
    op.drop_index("ix_training_samples_generation_run", table_name="training_samples")
    op.drop_index("ix_training_samples_parent", table_name="training_samples")
    op.drop_column("training_samples", "generation_run_id")
    op.drop_column("training_samples", "parent_sample_id")
