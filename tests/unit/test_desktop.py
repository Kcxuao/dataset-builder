import os
from pathlib import Path

from dataset_builder.desktop import application_data_dir, configure_desktop_environment, resource_root


def test_resource_root_finds_project_packaging_files() -> None:
    root = resource_root()

    assert (root / "alembic.ini").is_file()
    assert (root / "migrations").is_dir()


def test_application_data_dir_honors_explicit_override(monkeypatch, tmp_path: Path) -> None:
    override = tmp_path / "dataset-builder-home"
    monkeypatch.setenv("DATASET_BUILDER_HOME", str(override))

    assert application_data_dir() == override.resolve()


def test_configure_desktop_environment_sets_local_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_PROVIDER", raising=False)
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.delenv("EXPORT_DIR", raising=False)
    root = tmp_path / "bundle"
    data_dir = tmp_path / "data"

    configure_desktop_environment(root, data_dir)

    assert data_dir.is_dir()
    assert os.environ["DATABASE_PROVIDER"] == "sqlite"
    assert os.environ["SQLITE_PATH"] == str(data_dir / "dataset-builder.sqlite3")
    assert os.environ["EXPORT_DIR"] == str(data_dir / "exports")
    assert os.environ["DATASET_BUILDER_WEB_DIR"] == str(root / "dataset_builder" / "web")
