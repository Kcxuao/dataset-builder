"""Build a portable LLaMA-Factory SFT package without invoking training."""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from collections.abc import AsyncIterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from dataset_builder.exporters.files import JSONLExporter

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@dataclass(frozen=True, slots=True)
class LLaMAFactoryConfig:
    model_name_or_path: str
    template: str
    finetuning_type: str = "lora"
    cutoff_len: int = 2048
    num_train_epochs: float = 3.0
    learning_rate: float = 5e-5
    per_device_train_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    output_dir_name: str = "sft-output"
    pref_beta: float = 0.1
    pref_loss: str = "sigmoid"

    def validate(self) -> None:
        if not self.model_name_or_path.strip() or "\n" in self.model_name_or_path:
            raise ValueError("基础模型名称或路径不能为空")
        if len(self.model_name_or_path) > 500:
            raise ValueError("基础模型名称或路径不能超过 500 个字符")
        if not SAFE_NAME.fullmatch(self.template):
            raise ValueError("模型模板只能包含字母、数字、点、下划线和短横线")
        if self.finetuning_type not in {"lora", "full"}:
            raise ValueError("微调方式必须是 LoRA 或全量微调")
        if not 128 <= self.cutoff_len <= 131072:
            raise ValueError("截断长度必须在 128 到 131072 之间")
        if not 0 < self.num_train_epochs <= 100:
            raise ValueError("训练轮数必须大于 0 且不超过 100")
        if not 0 < self.learning_rate <= 1:
            raise ValueError("学习率必须大于 0 且不超过 1")
        if not 1 <= self.per_device_train_batch_size <= 1024:
            raise ValueError("单设备批次必须在 1 到 1024 之间")
        if not 1 <= self.gradient_accumulation_steps <= 1024:
            raise ValueError("梯度累积必须在 1 到 1024 之间")
        if not SAFE_NAME.fullmatch(self.output_dir_name):
            raise ValueError("输出目录名只能包含字母、数字、点、下划线和短横线")
        if not 0 < self.pref_beta <= 10:
            raise ValueError("DPO beta 必须大于 0 且不超过 10")
        if self.pref_loss not in {"sigmoid", "hinge", "ipo", "orpo", "simpo"}:
            raise ValueError("不支持的偏好损失类型")


class LLaMAFactoryPackageBuilder:
    DATASET_NAME = "dataset_builder_sft"

    async def build(
        self,
        records: AsyncIterable[dict[str, object]],
        destination: Path,
        config: LLaMAFactoryConfig,
        *,
        version_id: str,
        version_name: str,
        created_at: datetime,
        dataset_type: str = "sft",
    ) -> int:
        config.validate()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_zip: Path | None = None
        with tempfile.TemporaryDirectory(prefix="dataset-builder-llamafactory-") as workspace_name:
            workspace = Path(workspace_name)
            data_dir = workspace / "data"
            sample_count = await JSONLExporter().export(records, data_dir / "dataset.jsonl")
            if sample_count == 0:
                raise ValueError("数据集版本不包含可用于训练的样本")
            (data_dir / "dataset_info.json").write_text(
                json.dumps(self._dataset_info(dataset_type), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            config_name = "train_dpo.yaml" if dataset_type == "dpo" else "train_sft.yaml"
            (workspace / config_name).write_text(self._training_yaml(config, dataset_type), encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "target": "llamafactory",
                "dataset_format": "sharegpt",
                "dataset_type": dataset_type,
                "version": {"id": version_id, "name": version_name, "created_at": created_at.isoformat()},
                "sample_count": sample_count,
                "training": asdict(config),
            }
            (workspace / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (workspace / "README.md").write_text(
                self._readme(version_name, sample_count, dataset_type), encoding="utf-8"
            )
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as output:
                    temporary_zip = Path(output.name)
                with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(workspace.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(workspace).as_posix())
                os.replace(temporary_zip, destination)
            except BaseException:
                if temporary_zip is not None:
                    temporary_zip.unlink(missing_ok=True)
                raise
        return sample_count

    def _dataset_info(self, dataset_type: str) -> dict[str, object]:
        info = {
                "file_name": "dataset.jsonl",
                "formatting": "sharegpt",
                "columns": {"messages": "conversations"},
                "tags": {
                    "role_tag": "from",
                    "content_tag": "value",
                    "user_tag": "human",
                    "assistant_tag": "gpt",
                    "system_tag": "system",
                },
            }
        if dataset_type == "dpo":
            info["ranking"] = True
            info["columns"] = {"messages": "conversations", "chosen": "chosen", "rejected": "rejected"}
        return {self.DATASET_NAME: info}

    def _training_yaml(self, config: LLaMAFactoryConfig, dataset_type: str) -> str:
        def quote(value: str) -> str:
            return json.dumps(value, ensure_ascii=False)

        lines = [
            "### model",
            f"model_name_or_path: {quote(config.model_name_or_path.strip())}",
            "trust_remote_code: true",
            "",
            "### method",
            f"stage: {'dpo' if dataset_type == 'dpo' else 'sft'}",
            "do_train: true",
            f"finetuning_type: {config.finetuning_type}",
        ]
        if config.finetuning_type == "lora":
            lines.append("lora_target: all")
        if dataset_type == "dpo":
            lines.extend([f"pref_beta: {config.pref_beta}", f"pref_loss: {config.pref_loss}"])
        lines.extend([
            "",
            "### dataset",
            "dataset_dir: data",
            f"dataset: {self.DATASET_NAME}",
            f"template: {config.template}",
            f"cutoff_len: {config.cutoff_len}",
            "overwrite_cache: true",
            "preprocessing_num_workers: 4",
            "dataloader_num_workers: 0",
            "",
            "### output",
            f"output_dir: {quote('outputs/' + config.output_dir_name)}",
            "logging_steps: 10",
            "save_steps: 500",
            "plot_loss: true",
            "overwrite_output_dir: true",
            "",
            "### train",
            f"per_device_train_batch_size: {config.per_device_train_batch_size}",
            f"gradient_accumulation_steps: {config.gradient_accumulation_steps}",
            f"learning_rate: {config.learning_rate}",
            f"num_train_epochs: {config.num_train_epochs}",
            "lr_scheduler_type: cosine",
            "warmup_ratio: 0.1",
            "",
        ])
        return "\n".join(lines)

    @staticmethod
    def _readme(version_name: str, sample_count: int, dataset_type: str) -> str:
        config_name = "train_dpo.yaml" if dataset_type == "dpo" else "train_sft.yaml"
        label = "DPO 偏好对" if dataset_type == "dpo" else "ShareGPT 样本"
        return f"""# LLaMA-Factory 训练包

本包由 Dataset Builder 的不可变版本 `{version_name}` 生成，共 {sample_count} 条 {label}。

## 使用方式

1. 安装并进入 LLaMA-Factory 可运行环境。
2. 保持本压缩包解压后的目录结构不变。
3. 在解压目录中检查 `{config_name}` 的模型路径和训练参数。
4. 执行：`llamafactory-cli train {config_name}`

本包不包含模型权重、LLaMA-Factory 程序或远程服务凭据，也不会自动启动训练。
"""
