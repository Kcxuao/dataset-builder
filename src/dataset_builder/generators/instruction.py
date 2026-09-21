"""Generate instruction-response training samples from a source Chunk."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from dataset_builder.generators.conversation import ConversationResponse, validate_turn_mode
from dataset_builder.generators.prompts import resolve_prompt
from dataset_builder.llm import LLMClient
from dataset_builder.models import Chunk, Message, MessageRole, TrainingSample

INSTRUCTION_SYSTEM_PROMPT = resolve_prompt("instruction")


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
    def __init__(
        self,
        client: LLMClient,
        project_id: UUID,
        system_prompt: str = INSTRUCTION_SYSTEM_PROMPT,
        multi_turn: bool = False,
    ) -> None:
        self.client = client
        self.project_id = project_id
        self.system_prompt = system_prompt
        self.multi_turn = multi_turn

    async def generate(self, chunk: Chunk) -> list[TrainingSample]:
        if not chunk.content.strip():
            raise ValueError("Cannot generate instructions from an empty Chunk")
        response_model = ConversationResponse if self.multi_turn else InstructionResponse
        response = await self.client.generate(
            [
                Message(role=MessageRole.SYSTEM, content=self.system_prompt),
                Message(role=MessageRole.USER, content=chunk.content),
            ],
            response_model,
        )
        if self.multi_turn:
            for item in response.items:
                validate_turn_mode(item.messages, True)
            return [
                TrainingSample(
                    project_id=self.project_id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    messages=item.messages,
                    metadata={**chunk.metadata, "generator": "instruction", "multi_turn": True},
                )
                for item in response.items
            ]
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
