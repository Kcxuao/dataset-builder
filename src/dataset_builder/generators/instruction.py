"""Generate instruction-response training samples from a source Chunk."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from dataset_builder.llm import LLMClient
from dataset_builder.models import Chunk, Message, MessageRole, TrainingSample

INSTRUCTION_SYSTEM_PROMPT = (
    "根据提供的文本生成一个或多个可由文本支持的指令与回答。"
    '只返回一个 json 对象，不要解释或代码块，格式为 {"items": [{"instruction": "...", "response": "..."}]}。'
)


class InstructionItem(BaseModel):
    instruction: str
    response: str

    @field_validator("instruction", "response")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("instruction and response must not be blank")
        return value


class InstructionResponse(BaseModel):
    items: list[InstructionItem] = Field(min_length=1)


class InstructionGenerator:
    def __init__(self, client: LLMClient, project_id: UUID) -> None:
        self.client = client
        self.project_id = project_id

    async def generate(self, chunk: Chunk) -> list[TrainingSample]:
        if not chunk.content.strip():
            raise ValueError("Cannot generate instructions from an empty Chunk")
        response = await self.client.generate(
            [
                Message(role=MessageRole.SYSTEM, content=INSTRUCTION_SYSTEM_PROMPT),
                Message(role=MessageRole.USER, content=chunk.content),
            ],
            InstructionResponse,
        )
        return [
            TrainingSample(
                project_id=self.project_id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                messages=[
                    Message(role=MessageRole.USER, content=item.instruction),
                    Message(role=MessageRole.ASSISTANT, content=item.response),
                ],
                metadata={**chunk.metadata, "generator": "instruction"},
            )
            for item in response.items
        ]
