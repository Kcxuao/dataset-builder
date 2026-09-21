"""Track superseded samples."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_samples", sa.Column("superseded_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_training_samples_search",
        "training_samples",
        ["project_id", "review_status", "validation_status", "is_deleted", "superseded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_samples_search", table_name="training_samples")
    op.drop_column("training_samples", "superseded_at")
