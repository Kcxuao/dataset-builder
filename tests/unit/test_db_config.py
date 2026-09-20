import pytest

from dataset_builder.db.orm import Base
from dataset_builder.db.session import create_engine


def test_schema_contains_core_tables_and_lineage_foreign_keys() -> None:
    assert set(Base.metadata.tables) == {
        "projects", "source_documents", "chunks", "training_samples",
        "validation_issues", "pipeline_runs", "export_records",
    }
    foreign_keys = {
        fk.target_fullname for fk in Base.metadata.tables["training_samples"].foreign_keys
    }
    assert foreign_keys == {"projects.id", "source_documents.id", "chunks.id"}


def test_engine_requires_async_postgres_url() -> None:
    with pytest.raises(ValueError, match="postgresql\\+asyncpg"):
        create_engine("sqlite:///:memory:")
