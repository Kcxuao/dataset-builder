"""Workspace processing defaults and custom prompt templates."""

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataset_builder.db.orm import ModelConfigRow, PromptTemplateRow, WorkspaceSettingsRow
from dataset_builder.generators.prompts import list_prompt_presets


class WorkspaceSettingsInput(BaseModel):
    parser_workers: int = Field(ge=1, le=16)
    default_model_id: UUID | None = None


class PromptTemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mode: str
    instruction: str = Field(min_length=1)
    multi_turn: bool = False


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def settings(self) -> dict[str, object]:
        row = await self.session.get(WorkspaceSettingsRow, 1)
        return {"parser_workers": row.parser_workers if row else 1,
                "default_model_id": str(row.default_model_id) if row and row.default_model_id else None}

    async def save_settings(self, data: WorkspaceSettingsInput) -> dict[str, object]:
        if data.default_model_id:
            model = await self.session.get(ModelConfigRow, data.default_model_id)
            if model is None or model.archived_at is not None:
                raise ValueError("默认模型不存在或已归档")
        row = await self.session.get(WorkspaceSettingsRow, 1)
        if row is None:
            row = WorkspaceSettingsRow(id=1)
            self.session.add(row)
        row.parser_workers = data.parser_workers
        row.default_model_id = data.default_model_id
        await self.session.flush()
        return await self.settings()

    async def list_prompts(self) -> list[dict[str, object]]:
        builtins = [
            {"id": f"builtin:{mode}:{item['id']}", "name": item["name"], "mode": mode,
             "instruction": item["prompt"], "multi_turn": bool(item["multi_turn"]), "builtin": True}
            for mode, items in list_prompt_presets().items() for item in items
        ]
        rows = (await self.session.scalars(select(PromptTemplateRow).order_by(PromptTemplateRow.created_at))).all()
        return builtins + [self._view(row) for row in rows]

    async def create_prompt(self, data: PromptTemplateInput) -> dict[str, object]:
        self._validate_prompt(data)
        row = PromptTemplateRow(
            name=data.name.strip(), mode=data.mode, instruction=data.instruction.strip(), multi_turn=data.multi_turn
        )
        self.session.add(row)
        await self.session.flush()
        return self._view(row)

    async def update_prompt(self, prompt_id: UUID, data: PromptTemplateInput) -> dict[str, object]:
        self._validate_prompt(data)
        row = await self._prompt(prompt_id)
        row.name = data.name.strip()
        row.mode = data.mode
        row.instruction = data.instruction.strip()
        row.multi_turn = data.multi_turn
        await self.session.flush()
        return self._view(row)

    async def delete_prompt(self, prompt_id: UUID) -> None:
        await self.session.delete(await self._prompt(prompt_id))
        await self.session.flush()

    async def resolve_prompt(self, mode: str, prompt_id: str) -> tuple[str, str | None, bool]:
        if prompt_id.startswith("builtin:"):
            parts = prompt_id.split(":")
            if len(parts) != 3 or parts[1] != mode:
                raise ValueError("提示词与生成方式不匹配")
            return parts[2], None, False
        try:
            row = await self._prompt(UUID(prompt_id))
        except (ValueError, LookupError) as exc:
            raise ValueError("提示词模板不存在") from exc
        if row.mode != mode:
            raise ValueError("提示词与生成方式不匹配")
        return "custom", row.instruction, row.multi_turn

    async def _prompt(self, prompt_id: UUID) -> PromptTemplateRow:
        row = await self.session.get(PromptTemplateRow, prompt_id)
        if row is None:
            raise LookupError("提示词模板不存在")
        return row

    @staticmethod
    def _validate_prompt(data: PromptTemplateInput) -> None:
        valid_mode = data.mode in {"qa", "instruction", "augmentation"}
        if not valid_mode or not data.name.strip() or not data.instruction.strip():
            raise ValueError("提示词名称、类型和内容无效")

    @staticmethod
    def _view(row: PromptTemplateRow) -> dict[str, object]:
        return {"id": str(row.id), "name": row.name, "mode": row.mode,
                "instruction": row.instruction, "multi_turn": row.multi_turn, "builtin": False}
