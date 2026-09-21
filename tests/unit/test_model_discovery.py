from types import SimpleNamespace
from uuid import uuid4

import pytest

from dataset_builder.application.model_configs import ModelConfigInput, ModelConfigService
from dataset_builder.application.model_discovery import (
    ModelConnectionCheckInput,
    ModelConnectionService,
    ModelDiscoveryInput,
    ModelDiscoveryService,
    list_model_providers,
)
from dataset_builder.llm.client import OpenAICompatibleModelCatalog


class FakeCatalog:
    def __init__(self, models: list[dict[str, str]]) -> None:
        self.models = models
        self.closed = False

    async def list_models(self) -> list[dict[str, str]]:
        return self.models

    async def aclose(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, row: object | None = None) -> None:
        self.row = row

    async def get(self, _model: object, _model_id: object) -> object | None:
        return self.row


class FakeModelSDK:
    def __init__(self, data: list[object]) -> None:
        self.models = SimpleNamespace(list=self.list)
        self.data = data

    async def list(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.data)


class FakeRows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows


class FakeCheckSession:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def scalars(self, _query: object) -> FakeRows:
        return FakeRows(self.rows)


def test_model_providers_include_supported_domestic_services() -> None:
    providers = list_model_providers()
    assert [provider["id"] for provider in providers] == [
        "custom", "qwen", "deepseek", "zhipu", "minimax",
    ]
    assert providers[1]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.mark.asyncio
async def test_catalog_sorts_and_deduplicates_models() -> None:
    sdk = FakeModelSDK([
        SimpleNamespace(id="z-model", owned_by="vendor"),
        SimpleNamespace(id="a-model", owned_by=""),
        SimpleNamespace(id="z-model", owned_by="vendor-two"),
        SimpleNamespace(id=""),
    ])
    catalog = OpenAICompatibleModelCatalog("https://example.com/v1", api_key="secret", timeout=5, sdk=sdk)

    assert await catalog.list_models() == [
        {"id": "a-model"}, {"id": "z-model", "owned_by": "vendor-two"},
    ]


@pytest.mark.asyncio
async def test_discovery_uses_stored_key_only_when_address_is_unchanged() -> None:
    row = SimpleNamespace(id=uuid4(), archived_at=None, base_url="https://example.com/v1/", api_key="stored")
    session = FakeSession(row)
    catalog = FakeCatalog([{"id": "model-a"}])
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeCatalog:
        captured.update(kwargs)
        return catalog

    service = ModelDiscoveryService(session, factory)
    result = await service.discover(ModelDiscoveryInput(
        base_url="https://example.com/v1", model_id=row.id,
    ))

    assert result == {"models": [{"id": "model-a"}]}
    assert captured["api_key"].get_secret_value() == "stored"
    assert catalog.closed is True


@pytest.mark.asyncio
async def test_discovery_requires_a_new_key_after_address_change() -> None:
    row = SimpleNamespace(id=uuid4(), archived_at=None, base_url="https://example.com/v1", api_key="stored")
    service = ModelDiscoveryService(FakeSession(row), lambda **_kwargs: FakeCatalog([]))

    with pytest.raises(ValueError, match="填写新 API Key"):
        await service.discover(ModelDiscoveryInput(
            base_url="https://other.example.com/v1", model_id=row.id,
        ))


@pytest.mark.asyncio
async def test_update_requires_a_new_key_after_address_change() -> None:
    row = SimpleNamespace(id=uuid4(), archived_at=None, base_url="https://example.com/v1", api_key="stored")

    with pytest.raises(ValueError, match="填写新 API Key"):
        await ModelConfigService(FakeSession(row)).update(row.id, ModelConfigInput(
            name="config", base_url="https://other.example.com/v1", model="model-a",
        ))


@pytest.mark.asyncio
async def test_connection_check_reports_each_saved_model_independently() -> None:
    connected = SimpleNamespace(
        id=uuid4(), archived_at=None, base_url="https://one.example.com/v1", api_key="key-one",
        timeout=30, model="model-a",
    )
    unavailable = SimpleNamespace(
        id=uuid4(), archived_at=None, base_url="https://two.example.com/v1", api_key="key-two",
        timeout=30, model="model-b",
    )
    catalogs = {
        connected.base_url: FakeCatalog([{"id": "model-a"}]),
        unavailable.base_url: FakeCatalog([{"id": "other-model"}]),
    }

    def factory(**kwargs: object) -> FakeCatalog:
        return catalogs[kwargs["base_url"]]

    result = await ModelConnectionService(FakeCheckSession([connected, unavailable]), factory).check(
        ModelConnectionCheckInput(),
    )

    assert [(item["model_id"], item["status"]) for item in result["checks"]] == [
        (str(connected.id), "connected"), (str(unavailable.id), "unavailable"),
    ]
    assert result["checks"][1]["message"] == "当前模型未在服务列表中返回"
    assert all(catalog.closed for catalog in catalogs.values())


@pytest.mark.asyncio
async def test_connection_check_keeps_other_results_when_one_service_fails() -> None:
    healthy = SimpleNamespace(
        id=uuid4(), archived_at=None, base_url="https://healthy.example.com/v1", api_key=None,
        timeout=5, model="model-a",
    )
    broken = SimpleNamespace(
        id=uuid4(), archived_at=None, base_url="https://broken.example.com/v1", api_key=None,
        timeout=5, model="model-b",
    )

    class BrokenCatalog(FakeCatalog):
        async def list_models(self) -> list[dict[str, str]]:
            raise ValueError("无法连接模型服务")

    def factory(**kwargs: object) -> FakeCatalog:
        if kwargs["base_url"] == broken.base_url:
            return BrokenCatalog([])
        return FakeCatalog([{"id": "model-a"}])

    result = await ModelConnectionService(FakeCheckSession([healthy, broken]), factory).check(
        ModelConnectionCheckInput(),
    )

    assert [item["status"] for item in result["checks"]] == ["connected", "unavailable"]
    assert result["checks"][1]["message"] == "无法连接模型服务"
