"""Generate question-answer training samples from a source Chunk."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from dataset_builder.generators.prompts import resolve_prompt
from dataset_builder.llm import LLMClient
from dataset_builder.models import Chunk, Message, MessageRole, TrainingSample

QA_SYSTEM_PROMPT = resolve_prompt("qa")


class QAPair(BaseModel):
    question: str
    answer: str

    @field_validator("question", "answer")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question and answer must not be blank")
        return value


class QAResponse(BaseModel):
    pairs: list[QAPair] = Field(min_length=1)


class QAGenerator:
    def __init__(self, client: LLMClient, project_id: UUID, system_prompt: str = QA_SYSTEM_PROMPT) -> None:
        self.client = client
        self.project_id = project_id
        self.system_prompt = system_prompt

    async def generate(self, chunk: Chunk) -> list[TrainingSample]:
        if not chunk.content.strip():
            raise ValueError("Cannot generate QA from an empty Chunk")
        response = await self.client.generate(
            [
                Message(role=MessageRole.SYSTEM, content=self.system_prompt),
                Message(role=MessageRole.USER, content=chunk.content),
            ],
            QAResponse,
        )
        return [
            TrainingSample(
                project_id=self.project_id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                messages=[
                    Message(role=MessageRole.USER, content=pair.question),
                    Message(role=MessageRole.ASSISTANT, content=pair.answer),
                ],
                metadata={**chunk.metadata, "generator": "qa"},
            )
            for pair in response.pairs
        ]
