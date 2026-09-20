"""Generate question-answer training samples from a source Chunk."""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from dataset_builder.llm import LLMClient
from dataset_builder.models import Chunk, Message, MessageRole, TrainingSample

QA_SYSTEM_PROMPT = (
    "根据提供的文本生成一个或多个可由文本直接回答的问题与答案。"
    "只返回 JSON 对象，格式为 {\"pairs\": [{\"question\": \"...\", \"answer\": \"...\"}]}。"
)


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
    def __init__(self, client: LLMClient, project_id: UUID) -> None:
        self.client = client
        self.project_id = project_id

    async def generate(self, chunk: Chunk) -> list[TrainingSample]:
        if not chunk.content.strip():
            raise ValueError("Cannot generate QA from an empty Chunk")
        response = await self.client.generate(
            [
                Message(role=MessageRole.SYSTEM, content=QA_SYSTEM_PROMPT),
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
