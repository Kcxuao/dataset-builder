"""Add the default conversation mode to prompt templates."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prompt_templates",
        sa.Column("multi_turn", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("prompt_templates") as batch:
            batch.drop_column("multi_turn")
    else:
        op.drop_column("prompt_templates", "multi_turn")
