"""Desktop distribution entry point for the packaged web workspace."""

import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

import uvicorn
from alembic import command
from alembic.config import Config


def resource_root() -> Path:
    """Return the directory containing bundled static files and migrations."""
    candidates = []
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(Path(bundle_dir))
    candidates.append(Path(sys.argv[0]).resolve().parent)
    candidates.append(Path(__file__).resolve().parents[2])
    for candidate in candidates:
        if (candidate / "alembic.ini").is_file() and (candidate / "migrations").is_dir():
            return candidate
    raise RuntimeError("发布包缺少 alembic.ini 或 migrations 目录")


def application_data_dir() -> Path:
    """Return the persistent per-user directory for the desktop distribution."""
    configured = os.environ.get("DATASET_BUILDER_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "dataset-builder"


def configure_desktop_environment(root: Path, data_dir: Path) -> None:
    """Configure bundled resources and safe local-storage defaults."""
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATABASE_PROVIDER", "sqlite")
    os.environ.setdefault("SQLITE_PATH", str(data_dir / "dataset-builder.sqlite3"))
    os.environ.setdefault("EXPORT_DIR", str(data_dir / "exports"))
    os.environ["DATASET_BUILDER_WEB_DIR"] = str(root / "dataset_builder" / "web")


def upgrade_database(root: Path) -> None:
    """Upgrade the local database before serving the workspace."""
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")


def main() -> None:
    root = resource_root()
    configure_desktop_environment(root, application_data_dir())
    upgrade_database(root)

    from dataset_builder.api import create_app

    host = os.environ.get("DATASET_BUILDER_HOST", "127.0.0.1")
    port = int(os.environ.get("DATASET_BUILDER_PORT", "8000"))
    if os.environ.get("DATASET_BUILDER_OPEN_BROWSER", "true").lower() not in {"0", "false", "no"}:
        Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}/", new=2)).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
