from uuid import uuid4

import pytest
from pydantic import ValidationError

from dataset_builder.generators.conversation import ConversationResponse
from dataset_builder.generators.instruction import InstructionGenerator, InstructionResponse
from dataset_builder.models import Chunk, Message, MessageRole


class FakeLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self, messages: list[Message], response_model: type[InstructionResponse]
    ) -> InstructionResponse:
        self.calls += 1
        assert response_model is InstructionResponse
        assert [message.role for message in messages] == [MessageRole.SYSTEM, MessageRole.USER]
        return InstructionResponse.model_validate({"items": [
            {"instruction": " Summarize ", "response": " Summary "},
            {"instruction": " Explain ", "response": " Explanation "},
        ]})


@pytest.mark.asyncio
async def test_instruction_generator_creates_samples_with_lineage() -> None:
    project_id = uuid4()
    chunk = Chunk(document_id=uuid4(), index=0, content="Source", metadata={"source_name": "a.txt"})
    fake = FakeLLMClient()

    samples = await InstructionGenerator(fake, project_id).generate(chunk)

    assert len(samples) == 2
    assert fake.calls == 1
    assert samples[0].project_id == project_id
    assert samples[0].document_id == chunk.document_id
    assert samples[0].chunk_id == chunk.id
    assert [message.content for message in samples[0].messages] == ["Summarize", "Summary"]
    assert samples[0].metadata == {"source_name": "a.txt", "generator": "instruction"}


@pytest.mark.asyncio
async def test_instruction_generator_rejects_empty_chunk() -> None:
    fake = FakeLLMClient()
    with pytest.raises(ValueError, match="empty Chunk"):
        await InstructionGenerator(fake, uuid4()).generate(Chunk(document_id=uuid4(), index=0, content=" "))
    assert fake.calls == 0


def test_instruction_response_requires_nonblank_fields() -> None:
    with pytest.raises(ValidationError):
        InstructionResponse.model_validate({"items": [{"instruction": " ", "response": "A"}]})


@pytest.mark.asyncio
async def test_instruction_multi_turn_keeps_the_messages_together() -> None:
    class MultiTurnFake:
        async def generate(
            self, messages: list[Message], response_model: type[ConversationResponse]
        ) -> ConversationResponse:
            assert response_model is ConversationResponse
            return ConversationResponse.model_validate({"items": [{"messages": [
                {"role": "user", "content": "任务"},
                {"role": "assistant", "content": "结果"},
                {"role": "user", "content": "补充"},
                {"role": "assistant", "content": "补充结果"},
            ]}]})

    sample = (await InstructionGenerator(MultiTurnFake(), uuid4(), multi_turn=True).generate(
        Chunk(document_id=uuid4(), index=0, content="Source")
    ))[0]

    assert [message.content for message in sample.messages] == ["任务", "结果", "补充", "补充结果"]
