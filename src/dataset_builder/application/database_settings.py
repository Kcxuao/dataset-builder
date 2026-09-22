"""File-backed database connection settings for desktop distributions."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import URL, make_url, text

from dataset_builder.db.session import create_engine


class DatabaseConnectionInput(BaseModel):
    provider: Literal["sqlite", "postgresql"]
    sqlite_path: str | None = Field(default=None, max_length=2000)
    host: str | None = Field(default=None, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_provider_fields(self) -> "DatabaseConnectionInput":
        if self.provider == "postgresql":
            missing = [name for name in ("host", "database", "username") if not getattr(self, name)]
            if missing:
                raise ValueError(f"PostgreSQL 配置缺少：{', '.join(missing)}")
        return self


class DatabaseSettingsService:
    """Persist pending connection settings outside the selected database."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "database.json"

    def load(self) -> DatabaseConnectionInput | None:
        if not self.path.is_file():
            return None
        try:
            return DatabaseConnectionInput.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("数据库配置文件无效，请重新保存设置") from exc

    def resolve(self, value: DatabaseConnectionInput) -> DatabaseConnectionInput:
        if value.provider != "postgresql" or value.password:
            return value
        saved = self.load()
        if saved and saved.provider == "postgresql" and saved.password:
            return value.model_copy(update={"password": saved.password})
        raise ValueError("首次配置 PostgreSQL 时必须填写密码")

    def save(self, value: DatabaseConnectionInput) -> DatabaseConnectionInput:
        resolved = self.resolve(value)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(resolved.model_dump_json(indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        return resolved

    def database_url(self, value: DatabaseConnectionInput) -> str:
        if value.provider == "sqlite":
            path = Path(value.sqlite_path) if value.sqlite_path else self.data_dir / "dataset-builder.sqlite3"
            if not path.is_absolute():
                path = self.data_dir / path
            return f"sqlite+aiosqlite:///{path.expanduser().resolve()}"
        return URL.create(
            "postgresql+asyncpg",
            username=value.username,
            password=value.password,
            host=value.host,
            port=value.port,
            database=value.database,
        ).render_as_string(hide_password=False)

    async def test(self, value: DatabaseConnectionInput) -> None:
        resolved = self.resolve(value)
        engine = create_engine(self.database_url(resolved))
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    def environment(self) -> dict[str, str]:
        saved = self.load()
        if saved is None:
            return {}
        if saved.provider == "sqlite":
            url = make_url(self.database_url(saved))
            return {"DATABASE_PROVIDER": "sqlite", "SQLITE_PATH": url.database or ""}
        return {
            "DATABASE_PROVIDER": "postgresql",
            "DATABASE_URL": self.database_url(saved),
        }

    def response(self, current_provider: str, restart_required: bool = False) -> dict[str, object]:
        saved = self.load()
        if saved is None:
            saved = DatabaseConnectionInput(
                provider="sqlite", sqlite_path=str(self.data_dir / "dataset-builder.sqlite3")
            )
        return {
            "current_provider": current_provider,
            "restart_required": restart_required or saved.provider != current_provider,
            "saved": {
                **saved.model_dump(exclude={"password"}),
                "password_configured": bool(saved.password),
            },
        }
