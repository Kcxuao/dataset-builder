"""Add DPO preference pairs and immutable preference snapshots."""

import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dataset_versions",
        sa.Column("dataset_type", sa.String(length=16), nullable=False, server_default="sft"),
    )
    op.create_table(
        "preference_pairs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("context_messages", sa.JSON(), nullable=False),
        sa.Column("chosen_response", sa.JSON(), nullable=False),
        sa.Column("rejected_response", sa.JSON(), nullable=False),
        sa.Column("chosen_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id")),
        sa.Column("rejected_sample_id", sa.Uuid(), sa.ForeignKey("training_samples.id")),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("source_documents.id")),
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id")),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("source_decision_id", sa.Uuid(), sa.ForeignKey("training_samples.id")),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("validation_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_decision_id", name="uq_preference_pairs_source_decision"),
    )
    op.create_index("ix_preference_pairs_project_id", "preference_pairs", ["project_id"])
    op.create_index("ix_preference_pairs_document_id", "preference_pairs", ["document_id"])
    op.create_index("ix_preference_pairs_chunk_id", "preference_pairs", ["chunk_id"])
    op.create_index(
        "ix_preference_pairs_search",
        "preference_pairs",
        ["project_id", "review_status", "validation_status", "is_deleted"],
    )
    op.create_index("ix_preference_pairs_hash", "preference_pairs", ["project_id", "content_hash"])
    op.create_table(
        "preference_validation_issues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pair_id", sa.Uuid(), sa.ForeignKey("preference_pairs.id"), nullable=False),
        sa.Column("rule", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_preference_validation_issues_pair_id", "preference_validation_issues", ["pair_id"])
    op.create_table(
        "dataset_version_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("dataset_versions.id"), nullable=False),
        sa.Column("pair_id", sa.Uuid(), sa.ForeignKey("preference_pairs.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("context_messages", sa.JSON(), nullable=False),
        sa.Column("chosen_response", sa.JSON(), nullable=False),
        sa.Column("rejected_response", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("version_id", "pair_id", name="uq_dataset_version_preferences_pair"),
    )
    op.create_index("ix_dataset_version_preferences_version_id", "dataset_version_preferences", ["version_id"])
    op.create_index(
        "ix_dataset_version_preferences_ordinal", "dataset_version_preferences", ["version_id", "ordinal"]
    )
    _backfill_distillation_preferences()


def _backfill_distillation_preferences() -> None:
    connection = op.get_bind()
    samples = sa.table(
        "training_samples",
        sa.column("id", sa.Uuid()), sa.column("project_id", sa.Uuid()), sa.column("document_id", sa.Uuid()),
        sa.column("chunk_id", sa.Uuid()), sa.column("messages", sa.JSON()), sa.column("metadata", sa.JSON()),
    )
    pairs = sa.table(
        "preference_pairs",
        sa.column("id", sa.Uuid()), sa.column("project_id", sa.Uuid()), sa.column("context_messages", sa.JSON()),
        sa.column("chosen_response", sa.JSON()), sa.column("rejected_response", sa.JSON()),
        sa.column("chosen_sample_id", sa.Uuid()), sa.column("rejected_sample_id", sa.Uuid()),
        sa.column("document_id", sa.Uuid()), sa.column("chunk_id", sa.Uuid()), sa.column("source_type", sa.String()),
        sa.column("source_decision_id", sa.Uuid()), sa.column("content_hash", sa.String()),
        sa.column("metadata", sa.JSON()), sa.column("review_status", sa.String()),
        sa.column("validation_status", sa.String()), sa.column("is_deleted", sa.Boolean()),
    )
    rows = connection.execute(sa.select(samples)).mappings().all()
    by_id = {str(row["id"]): row for row in rows}
    inserts = []
    for candidate in rows:
        metadata = candidate["metadata"] or {}
        decision = metadata.get("distillation_decision")
        source = by_id.get(str(metadata.get("distillation_source_id")))
        if decision not in {"adopt_teacher", "keep_original"} or source is None:
            continue
        first, second = (candidate, source) if decision == "adopt_teacher" else (source, candidate)
        chosen_messages, rejected_messages = first["messages"] or [], second["messages"] or []
        if len(chosen_messages) < 2 or len(rejected_messages) < 2:
            continue
        context = chosen_messages[:-1]
        chosen, rejected = chosen_messages[-1], rejected_messages[-1]
        invalid_responses = chosen.get("role") != "assistant" or rejected.get("role") != "assistant"
        if context != rejected_messages[:-1] or invalid_responses:
            continue
        normalized = {
            "context": [{"role": item["role"], "content": item["content"].strip()} for item in context],
            "chosen": {"role": "assistant", "content": chosen.get("content", "").strip()},
            "rejected": {"role": "assistant", "content": rejected.get("content", "").strip()},
        }
        if not normalized["chosen"]["content"] or normalized["chosen"]["content"] == normalized["rejected"]["content"]:
            continue
        digest = hashlib.sha256(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        inserts.append({
            "id": uuid4(), "project_id": candidate["project_id"], "context_messages": context,
            "chosen_response": chosen, "rejected_response": rejected, "chosen_sample_id": first["id"],
            "rejected_sample_id": second["id"], "document_id": candidate["document_id"],
            "chunk_id": candidate["chunk_id"], "source_type": "distillation_review",
            "source_decision_id": candidate["id"], "content_hash": digest,
            "metadata": {"distillation_decision": decision}, "review_status": "approved",
            "validation_status": "passed", "is_deleted": False,
        })
    if inserts:
        connection.execute(sa.insert(pairs), inserts)


def downgrade() -> None:
    op.drop_index("ix_dataset_version_preferences_ordinal", table_name="dataset_version_preferences")
    op.drop_index("ix_dataset_version_preferences_version_id", table_name="dataset_version_preferences")
    op.drop_table("dataset_version_preferences")
    op.drop_index("ix_preference_validation_issues_pair_id", table_name="preference_validation_issues")
    op.drop_table("preference_validation_issues")
    op.drop_index("ix_preference_pairs_hash", table_name="preference_pairs")
    op.drop_index("ix_preference_pairs_search", table_name="preference_pairs")
    op.drop_index("ix_preference_pairs_chunk_id", table_name="preference_pairs")
    op.drop_index("ix_preference_pairs_document_id", table_name="preference_pairs")
    op.drop_index("ix_preference_pairs_project_id", table_name="preference_pairs")
    op.drop_table("preference_pairs")
    op.drop_column("dataset_versions", "dataset_type")
