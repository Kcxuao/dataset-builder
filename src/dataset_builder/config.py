"""Application configuration loaded from environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_provider: Literal["postgresql", "sqlite"] = "postgresql"
    database_url: str | None = None
    sqlite_path: Path = Path("dataset-builder.sqlite3")
    export_dir: Path = Path("exports")

    @model_validator(mode="after")
    def validate_database_configuration(self) -> "Settings":
        if self.database_provider == "postgresql" and not self.database_url:
            raise ValueError("DATABASE_URL is required when DATABASE_PROVIDER=postgresql")
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_provider == "sqlite":
            return f"sqlite+aiosqlite:///{self.sqlite_path.resolve()}"
        if not self.database_url or not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg dialect")
        return self.database_url


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LLM_", extra="ignore")

    base_url: str
    api_key: SecretStr = SecretStr("not-needed")
    model: str
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, gt=0)
    timeout: float = Field(default=60, gt=0)
    concurrency_limit: int = Field(default=4, gt=0)
    max_retries: int = Field(default=2, ge=0)
    json_mode: bool = False
    thinking: bool | None = None
