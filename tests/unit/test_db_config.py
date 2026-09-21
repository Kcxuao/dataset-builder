import pytest

from dataset_builder.config import Settings
from dataset_builder.db.orm import Base
from dataset_builder.db.session import create_engine


def test_schema_contains_core_tables_and_lineage_foreign_keys() -> None:
    assert set(Base.metadata.tables) == {
        "projects", "source_documents", "chunks", "training_samples",
        "validation_issues", "pipeline_runs", "export_records", "model_configs",
        "workspace_settings", "prompt_templates", "augmentation_jobs", "distillation_jobs",
        "dataset_versions", "dataset_version_samples",
    }
    foreign_keys = {
        fk.target_fullname for fk in Base.metadata.tables["training_samples"].foreign_keys
    }
    assert foreign_keys == {
        "projects.id", "source_documents.id", "chunks.id", "training_samples.id", "pipeline_runs.id"
    }
    job_keys = {fk.target_fullname for fk in Base.metadata.tables["augmentation_jobs"].foreign_keys}
    assert job_keys == {"pipeline_runs.id", "training_samples.id"}
    version_keys = {fk.target_fullname for fk in Base.metadata.tables["dataset_version_samples"].foreign_keys}
    assert version_keys == {"dataset_versions.id", "training_samples.id", "source_documents.id", "chunks.id"}


def test_engine_supports_postgres_and_async_sqlite_urls() -> None:
    postgres = create_engine("postgresql+asyncpg://user:pass@localhost/dataset")
    sqlite = create_engine("sqlite+aiosqlite:////tmp/dataset.sqlite3")

    assert postgres.url.drivername == "postgresql+asyncpg"
    assert sqlite.url.drivername == "sqlite+aiosqlite"
    with pytest.raises(ValueError, match="postgresql\\+asyncpg or sqlite\\+aiosqlite"):
        create_engine("sqlite:///:memory:")


def test_settings_selects_local_sqlite_without_reusing_postgres_url(tmp_path) -> None:
    settings = Settings(
        database_provider="sqlite",
        database_url="postgresql+asyncpg://user:pass@localhost/ignored",
        sqlite_path=tmp_path / "local.sqlite3",
    )

    assert settings.resolved_database_url == f"sqlite+aiosqlite:///{(tmp_path / 'local.sqlite3').resolve()}"
