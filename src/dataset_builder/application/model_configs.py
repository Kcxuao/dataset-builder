"""Persist and select compatible model configurations."""

from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.config import LLMSettings
from dataset_builder.db.orm import ModelConfigRow


class ModelConfigInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: AnyHttpUrl
    api_key: SecretStr | None = None
    model: str = Field(min_length=1, max_length=255)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1024, gt=0)
    timeout: float = Field(default=60, gt=0)
    concurrency_limit: int = Field(default=4, ge=1, le=32)
    max_retries: int = Field(default=2, ge=0, le=10)
    json_mode: bool = False
    thinking: bool | None = None


class ModelConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_models(self) -> list[dict[str, object]]:
        query = select(ModelConfigRow).order_by(ModelConfigRow.created_at, ModelConfigRow.name)
        rows = (await self.session.scalars(query)).all()
        return [self._view(row) for row in rows]

    async def create(self, data: ModelConfigInput) -> dict[str, object]:
        name = data.name.strip()
        model = data.model.strip()
        if not name or not model:
            raise ValueError("配置名称和模型名称不能为空")
        existing = await self.session.scalar(select(ModelConfigRow.id).where(ModelConfigRow.name == name))
        if existing is not None:
            raise ValueError("该模型配置名称已存在")
        row = ModelConfigRow(
            name=name, base_url=str(data.base_url),
            api_key=data.api_key.get_secret_value() if data.api_key else None,
            model=model, temperature=data.temperature, max_tokens=data.max_tokens,
            timeout=data.timeout, concurrency_limit=data.concurrency_limit,
            max_retries=data.max_retries, json_mode=data.json_mode, thinking=data.thinking,
        )
        self.session.add(row)
        await self.session.flush()
        return self._view(row)

    async def settings_for(self, model_id: UUID) -> LLMSettings:
        row = await self.session.get(ModelConfigRow, model_id)
        if row is None:
            raise LookupError("模型配置不存在")
        return LLMSettings(
            base_url=row.base_url, api_key=SecretStr(row.api_key or "not-needed"), model=row.model,
            temperature=row.temperature, max_tokens=row.max_tokens, timeout=row.timeout,
            concurrency_limit=row.concurrency_limit, max_retries=row.max_retries,
            json_mode=row.json_mode, thinking=row.thinking,
        )

    @staticmethod
    def _view(row: ModelConfigRow) -> dict[str, object]:
        return {
            "id": str(row.id), "name": row.name, "base_url": row.base_url,
            "model": row.model, "has_api_key": bool(row.api_key),
            "temperature": row.temperature, "max_tokens": row.max_tokens,
            "timeout": row.timeout, "concurrency_limit": row.concurrency_limit,
            "max_retries": row.max_retries, "json_mode": row.json_mode,
            "thinking": row.thinking, "created_at": row.created_at,
        }
