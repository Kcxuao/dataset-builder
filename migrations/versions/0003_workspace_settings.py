"""Add configuration pages and project trash.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("model_configs", sa.Column("family_id", sa.Uuid()))
    op.add_column("model_configs", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE model_configs SET family_id = id")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_configs") as batch:
            batch.alter_column("family_id", existing_type=sa.Uuid(), nullable=False)
            batch.drop_constraint("model_configs_name_key", type_="unique")
    else:
        op.alter_column("model_configs", "family_id", nullable=False)
        op.drop_constraint("model_configs_name_key", "model_configs", type_="unique")
    op.create_index("ix_model_configs_family_id", "model_configs", ["family_id"])
    op.create_index(
        "uq_model_configs_active_name", "model_configs", ["name"], unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
        sqlite_where=sa.text("archived_at IS NULL"),
    )
    op.create_table(
        "workspace_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parser_workers", sa.Integer(), nullable=False),
        sa.Column("default_model_id", sa.Uuid(), sa.ForeignKey("model_configs.id")),
    )
    op.execute("INSERT INTO workspace_settings (id, parser_workers) VALUES (1, 1)")
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("prompt_templates")
    op.drop_table("workspace_settings")
    op.drop_index("uq_model_configs_active_name", table_name="model_configs")
    op.drop_index("ix_model_configs_family_id", table_name="model_configs")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_configs") as batch:
            batch.create_unique_constraint("model_configs_name_key", ["name"])
            batch.drop_column("archived_at")
            batch.drop_column("family_id")
    else:
        op.create_unique_constraint("model_configs_name_key", "model_configs", ["name"])
        op.drop_column("model_configs", "archived_at")
        op.drop_column("model_configs", "family_id")
    op.drop_column("projects", "deleted_at")
