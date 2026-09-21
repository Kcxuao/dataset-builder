import json
import zipfile
from datetime import UTC, datetime

import pytest

from dataset_builder.training_targets import LLaMAFactoryConfig, LLaMAFactoryPackageBuilder


async def records():
    yield {
        "conversations": [
            {"from": "system", "value": "专业助手"},
            {"from": "human", "value": "第一问"},
            {"from": "gpt", "value": "第一答"},
            {"from": "human", "value": "第二问"},
            {"from": "gpt", "value": "第二答"},
        ]
    }


@pytest.mark.asyncio
async def test_build_llamafactory_package_preserves_multiturn_and_writes_config(tmp_path) -> None:
    destination = tmp_path / "package.zip"
    config = LLaMAFactoryConfig(
        model_name_or_path="Qwen/Qwen2.5-7B-Instruct",
        template="qwen",
        output_dir_name="release-v1",
    )

    count = await LLaMAFactoryPackageBuilder().build(
        records(),
        destination,
        config,
        version_id="version-id",
        version_name="v1.0",
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert count == 1
    with zipfile.ZipFile(destination) as package:
        assert set(package.namelist()) == {
            "README.md",
            "data/dataset.jsonl",
            "data/dataset_info.json",
            "manifest.json",
            "train_sft.yaml",
        }
        sample = json.loads(package.read("data/dataset.jsonl"))
        assert [message["from"] for message in sample["conversations"]] == [
            "system", "human", "gpt", "human", "gpt"
        ]
        dataset_info = json.loads(package.read("data/dataset_info.json"))
        assert dataset_info["dataset_builder_sft"]["formatting"] == "sharegpt"
        yaml = package.read("train_sft.yaml").decode()
        assert 'model_name_or_path: "Qwen/Qwen2.5-7B-Instruct"' in yaml
        assert "dataset_dir: data" in yaml
        assert "finetuning_type: lora" in yaml
        assert 'output_dir: "outputs/release-v1"' in yaml
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["sample_count"] == 1
        assert manifest["version"]["id"] == "version-id"


def test_llamafactory_config_rejects_unsafe_output_directory() -> None:
    with pytest.raises(ValueError, match="输出目录名"):
        LLaMAFactoryConfig(
            model_name_or_path="model",
            template="qwen",
            output_dir_name="../outside",
        ).validate()
