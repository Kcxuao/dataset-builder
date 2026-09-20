"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    export_dir: Path = Path("exports")


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
