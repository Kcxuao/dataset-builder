import json
import os
from pathlib import Path

import httpx
import pytest

from dataset_builder.api import create_app
from dataset_builder.application.database_settings import DatabaseConnectionInput, DatabaseSettingsService


def postgres_input(password: str | None = "secret") -> DatabaseConnectionInput:
    return DatabaseConnectionInput(
        provider="postgresql",
        host="db.internal",
        port=5433,
        database="datasets",
        username="builder",
        password=password,
    )


def test_database_settings_hide_and_retain_saved_password(tmp_path: Path) -> None:
    service = DatabaseSettingsService(tmp_path)
    service.save(postgres_input())

    saved = service.save(postgres_input(password=None))
    response = service.response("sqlite", restart_required=True)

    assert saved.password == "secret"
    assert "password" not in response["saved"]
    assert response["saved"]["password_configured"] is True
    assert response["restart_required"] is True
    assert json.loads(service.path.read_text(encoding="utf-8"))["password"] == "secret"
    if os.name != "nt":
        assert service.path.stat().st_mode & 0o777 == 0o600


def test_database_settings_build_environment_for_sqlite(tmp_path: Path) -> None:
    service = DatabaseSettingsService(tmp_path)
    service.save(DatabaseConnectionInput(provider="sqlite", sqlite_path="storage/local.sqlite3"))

    environment = service.environment()

    assert environment == {
        "DATABASE_PROVIDER": "sqlite",
        "SQLITE_PATH": str((tmp_path / "storage/local.sqlite3").resolve()),
    }


def test_postgres_requires_password_on_first_save(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="必须填写密码"):
        DatabaseSettingsService(tmp_path).save(postgres_input(password=None))


@pytest.mark.asyncio
async def test_database_settings_api_saves_without_returning_password(monkeypatch, tmp_path: Path) -> None:
    async def fake_test(self, value):
        assert value.host == "db.internal"

    monkeypatch.setattr(DatabaseSettingsService, "test", fake_test)
    app = create_app(database_config_dir=tmp_path)
    payload = postgres_input().model_dump()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        tested = await client.post("/api/system/database-settings/test", json=payload)
        saved = await client.put("/api/system/database-settings", json=payload)
        loaded = await client.get("/api/system/database-settings")

    assert tested.json() == {"ok": True, "message": "连接成功"}
    assert saved.status_code == 200
    assert saved.json()["restart_required"] is True
    assert "password" not in loaded.json()["saved"]
    assert loaded.json()["saved"]["password_configured"] is True


@pytest.mark.asyncio
async def test_database_status_returns_boolean_configurable_flag(tmp_path: Path) -> None:
    app = create_app(database_config_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/system/database")

    assert response.status_code == 200
    assert response.json()["configurable"] is True
