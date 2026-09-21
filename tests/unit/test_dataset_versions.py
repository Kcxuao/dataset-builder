from uuid import uuid4

from dataset_builder.application.versions import DatasetVersionService
from dataset_builder.db.orm import DatasetVersionRow, DatasetVersionSampleRow


def version_sample(sample_id, version_id, content_hash, metadata=None):
    return DatasetVersionSampleRow(
        id=uuid4(),
        version_id=version_id,
        sample_id=sample_id,
        document_id=uuid4(),
        chunk_id=uuid4(),
        ordinal=0,
        messages=[{"role": "user", "content": "问题"}, {"role": "assistant", "content": "回答"}],
        metadata_=metadata or {},
        content_hash=content_hash,
    )


def test_version_comparison_detects_added_removed_changed_and_replaced_samples() -> None:
    project_id, base_id, target_id = uuid4(), uuid4(), uuid4()
    removed_id, changed_id, added_id = uuid4(), uuid4(), uuid4()
    base = DatasetVersionRow(
        id=base_id, project_id=project_id, name="v1", sample_count=2, statistics={}, description=None
    )
    target = DatasetVersionRow(
        id=target_id, project_id=project_id, name="v2", sample_count=2, statistics={}, description=None
    )
    base_rows = [version_sample(removed_id, base_id, "old-a"), version_sample(changed_id, base_id, "old-b")]
    target_rows = [
        version_sample(changed_id, target_id, "new-b"),
        version_sample(
            added_id,
            target_id,
            "new-c",
            {"generator": "distillation", "distillation_source_id": str(removed_id)},
        ),
    ]

    result = DatasetVersionService._comparison(base, target, base_rows, target_rows)

    assert result["counts"] == {"added": 1, "removed": 1, "changed": 1, "replaced": 1}
    assert result["added"][0]["origin"] == "distillation"
