"""Discover models and check OpenAI Compatible service connectivity."""

import asyncio
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.application.model_configs import ModelConfigService
from dataset_builder.db.orm import ModelConfigRow
from dataset_builder.models import utc_now


class ModelProvider(BaseModel):
    """A selectable service preset for the model configuration form."""

    id: str
    name: str
    base_url: str | None = None


MODEL_PROVIDERS = (
    ModelProvider(id="custom", name="自定义 OpenAI Compatible 服务"),
    ModelProvider(
        id="qwen",
        name="阿里云百炼（Qwen）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
    ModelProvider(id="deepseek", name="DeepSeek", base_url="https://api.deepseek.com/v1"),
    ModelProvider(id="zhipu", name="智谱 AI", base_url="https://open.bigmodel.cn/api/paas/v4/"),
    ModelProvider(id="minimax", name="MiniMax", base_url="https://api.minimax.io/v1"),
)


class ModelDiscoveryInput(BaseModel):
    base_url: AnyHttpUrl
    api_key: SecretStr | None = None
    model_id: UUID | None = None
    timeout: float = Field(default=15, gt=0, le=60)


class ModelConnectionCheckInput(BaseModel):
    model_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ModelCatalog(Protocol):
    async def list_models(self) -> list[dict[str, str]]: ...

    async def aclose(self) -> None: ...


ModelCatalogFactory = Callable[..., ModelCatalog]


def list_model_providers() -> list[dict[str, str | None]]:
    return [provider.model_dump() for provider in MODEL_PROVIDERS]


class ModelDiscoveryService:
    def __init__(self, session: AsyncSession, catalog_factory: ModelCatalogFactory) -> None:
        self.session = session
        self.catalog_factory = catalog_factory

    async def discover(self, data: ModelDiscoveryInput) -> dict[str, list[dict[str, str]]]:
        api_key = await self._api_key_for(data)
        catalog = self.catalog_factory(
            base_url=str(data.base_url), api_key=api_key, timeout=data.timeout,
        )
        try:
            return {"models": await catalog.list_models()}
        finally:
            await catalog.aclose()

    async def _api_key_for(self, data: ModelDiscoveryInput) -> SecretStr:
        if data.api_key is not None:
            return data.api_key
        if data.model_id is None:
            return SecretStr("not-needed")

        model = await ModelConfigService(self.session).active_model(data.model_id)
        if _normalized_url(str(data.base_url)) != _normalized_url(model.base_url) and model.api_key:
            raise ValueError("已修改接口地址，请填写新 API Key 后再拉取模型")
        return SecretStr(model.api_key or "not-needed")


def _normalized_url(value: str) -> str:
    return value.rstrip("/")


class ModelConnectionService:
    """Check saved model configurations without making a generation request."""

    def __init__(self, session: AsyncSession, catalog_factory: ModelCatalogFactory) -> None:
        self.session = session
        self.catalog_factory = catalog_factory

    async def check(self, data: ModelConnectionCheckInput) -> dict[str, list[dict[str, object]]]:
        query = select(ModelConfigRow).where(ModelConfigRow.archived_at.is_(None)).order_by(
            ModelConfigRow.created_at, ModelConfigRow.name,
        )
        if data.model_ids:
            query = query.where(ModelConfigRow.id.in_(data.model_ids))
        rows = (await self.session.scalars(query)).all()
        semaphore = asyncio.Semaphore(4)

        async def check_row(row: ModelConfigRow) -> dict[str, object]:
            async with semaphore:
                return await self._check_row(row)

        return {"checks": list(await asyncio.gather(*(check_row(row) for row in rows)))}

    async def _check_row(self, row: ModelConfigRow) -> dict[str, object]:
        checked_at = utc_now()
        catalog: ModelCatalog | None = None
        try:
            catalog = self.catalog_factory(
                base_url=row.base_url,
                api_key=SecretStr(row.api_key or "not-needed"),
                timeout=min(row.timeout, 15),
            )
            models = await catalog.list_models()
            if any(item["id"] == row.model for item in models):
                return self._result(row.id, "connected", checked_at)
            return self._result(row.id, "unavailable", checked_at, "当前模型未在服务列表中返回")
        except ValueError as exc:
            return self._result(row.id, "unavailable", checked_at, str(exc))
        except Exception:
            return self._result(row.id, "unavailable", checked_at, "连接检查失败，请稍后重试")
        finally:
            if catalog is not None:
                await catalog.aclose()

    @staticmethod
    def _result(
        model_id: UUID, status: str, checked_at: object, message: str | None = None,
    ) -> dict[str, object]:
        return {
            "model_id": str(model_id), "status": status, "checked_at": checked_at, "message": message,
        }
