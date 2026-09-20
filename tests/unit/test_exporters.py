import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from dataset_builder.exporters import JSONExporter, JSONLExporter
from dataset_builder.formatters import AlpacaFormatter, FormatError, ShareGPTFormatter
from dataset_builder.models import Message, TrainingSample


def sample(*messages: tuple[str, str]) -> TrainingSample:
    return TrainingSample(
        project_id=uuid4(), document_id=uuid4(), chunk_id=uuid4(),
        messages=[Message(role=role, content=content) for role, content in messages],
    )


def test_formatters_map_single_and_multi_turn_messages() -> None:
    single = sample(("user", "问题"), ("assistant", "答案"))
    multi = sample(("system", "助手"), ("user", "问题"), ("assistant", "答案"))

    assert AlpacaFormatter().format(single) == {"instruction": "问题", "input": "", "output": "答案"}
    assert ShareGPTFormatter().format(multi) == {"conversations": [
        {"from": "system", "value": "助手"},
        {"from": "human", "value": "问题"},
        {"from": "gpt", "value": "答案"},
    ]}


def test_alpaca_rejects_lossy_multi_turn_conversion() -> None:
    multi = sample(("user", "Q1"), ("assistant", "A1"), ("user", "Q2"), ("assistant", "A2"))

    with pytest.raises(FormatError) as caught:
        AlpacaFormatter().format(multi)

    assert any(issue.rule == "formatter_incompatible" for issue in caught.value.issues)
    assert all(issue.sample_id == multi.id for issue in caught.value.issues)


async def records() -> AsyncIterator[dict[str, object]]:
    yield {"text": "中文"}
    yield {"text": "second"}


@pytest.mark.asyncio
@pytest.mark.parametrize("exporter,extension", [(JSONExporter(), "json"), (JSONLExporter(), "jsonl")])
async def test_exporters_write_incrementally(tmp_path, exporter, extension: str) -> None:
    destination = tmp_path / f"data.{extension}"

    count = await exporter.export(records(), destination)

    assert count == 2
    text = destination.read_text(encoding="utf-8")
    decoded = json.loads(text) if extension == "json" else [json.loads(line) for line in text.splitlines()]
    assert decoded == [{"text": "中文"}, {"text": "second"}]


@pytest.mark.asyncio
async def test_exporter_keeps_previous_file_on_stream_failure(tmp_path) -> None:
    destination = tmp_path / "data.jsonl"
    destination.write_text("previous", encoding="utf-8")

    async def failing_records() -> AsyncIterator[dict[str, object]]:
        yield {"text": "first"}
        raise ValueError("format failed")

    with pytest.raises(ValueError, match="format failed"):
        await JSONLExporter().export(failing_records(), destination)

    assert destination.read_text(encoding="utf-8") == "previous"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data.jsonl"]


@pytest.mark.asyncio
async def test_empty_json_export_is_array(tmp_path) -> None:
    async def empty() -> AsyncIterator[dict[str, object]]:
        if False:
            yield {}

    destination = tmp_path / "empty.json"
    assert await JSONExporter().export(empty(), destination) == 0
    assert destination.read_text(encoding="utf-8") == "[]"
