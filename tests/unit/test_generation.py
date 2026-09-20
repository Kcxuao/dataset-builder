import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dataset_builder.config import LLMSettings
from dataset_builder.generators.qa import QAGenerator, QAResponse
from dataset_builder.llm.client import LLMResponseError, OpenAICompatibleClient, parse_response
from dataset_builder.models import Chunk, Message, MessageRole


class FakeLLMClient:
    def __init__(self, response: QAResponse) -> None:
        self.response = response
        self.calls: list[list[Message]] = []

    async def generate(self, messages: list[Message], response_model: type[QAResponse]) -> QAResponse:
        self.calls.append(messages)
        assert response_model is QAResponse
        return self.response


class FakeSDK:
    def __init__(self, responses: list[str | None]) -> None:
        self.responses = iter(responses)
        self.calls = 0
        self.kwargs: list[dict[str, object]] = []
        self.active = 0
        self.peak = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.kwargs.append(kwargs)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        content = next(self.responses)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def settings(**overrides: object) -> LLMSettings:
    values = {"base_url": "http://localhost:8000/v1", "model": "fake-model", "max_retries": 0, **overrides}
    return LLMSettings.model_validate(values)


@pytest.mark.asyncio
async def test_qa_generator_creates_samples_with_lineage_and_metadata() -> None:
    project_id, document_id = uuid4(), uuid4()
    chunk = Chunk(document_id=document_id, index=0, content="Source text", metadata={"source_name": "guide.md"})
    fake = FakeLLMClient(QAResponse.model_validate({"pairs": [
        {"question": " What? ", "answer": " Answer "},
        {"question": "Why?", "answer": "Because."},
    ]}))

    samples = await QAGenerator(fake, project_id).generate(chunk)

    assert len(samples) == 2
    assert samples[0].project_id == project_id
    assert samples[0].document_id == document_id
    assert samples[0].chunk_id == chunk.id
    assert [(message.role, message.content) for message in samples[0].messages] == [
        (MessageRole.USER, "What?"), (MessageRole.ASSISTANT, "Answer")
    ]
    assert samples[0].metadata == {"source_name": "guide.md", "generator": "qa"}
    assert [message.role for message in fake.calls[0]] == [MessageRole.SYSTEM, MessageRole.USER]


@pytest.mark.asyncio
async def test_empty_chunk_does_not_call_llm() -> None:
    fake = FakeLLMClient(QAResponse.model_validate({"pairs": [{"question": "Q", "answer": "A"}]}))
    with pytest.raises(ValueError, match="empty Chunk"):
        await QAGenerator(fake, uuid4()).generate(Chunk(document_id=uuid4(), index=0, content="  "))
    assert fake.calls == []


@pytest.mark.parametrize("text", [
    '```json\n{"pairs": [{"question": "Q", "answer": "A"}]}\n```',
    '{"pairs": [{"question": "Q", "answer": "A"}]}',
])
def test_response_parser_accepts_json_and_code_fences(text: str) -> None:
    assert parse_response(text, QAResponse).pairs[0].question == "Q"


@pytest.mark.parametrize("text", [None, "{", '{"pairs": [{"question": "Q"}]}'])
def test_response_parser_rejects_missing_and_invalid_json(text: str | None) -> None:
    with pytest.raises(LLMResponseError):
        parse_response(text, QAResponse)


def test_qa_schema_rejects_blank_fields() -> None:
    with pytest.raises(ValidationError):
        QAResponse.model_validate({"pairs": [{"question": " ", "answer": "A"}]})


@pytest.mark.asyncio
async def test_client_retries_invalid_response_then_validates() -> None:
    sdk = FakeSDK(["{", '{"pairs": [{"question": "Q", "answer": "A"}]}'])
    client = OpenAICompatibleClient(settings(max_retries=1), sdk=sdk)

    result = await client.generate([Message(role=MessageRole.USER, content="Source")], QAResponse)

    assert result.pairs[0].answer == "A"
    assert sdk.calls == 2
    assert sdk.kwargs[0]["model"] == "fake-model"
    assert sdk.kwargs[0]["max_tokens"] == 1024
    assert sdk.kwargs[0]["messages"] == [{"role": "user", "content": "Source"}]


@pytest.mark.asyncio
async def test_client_exhausts_retries_on_invalid_response() -> None:
    sdk = FakeSDK(["{", "{"])
    client = OpenAICompatibleClient(settings(max_retries=1), sdk=sdk)
    with pytest.raises(LLMResponseError):
        await client.generate([Message(role=MessageRole.USER, content="Source")], QAResponse)
    assert sdk.calls == 2


@pytest.mark.asyncio
async def test_client_limits_concurrent_calls() -> None:
    response = '{"pairs": [{"question": "Q", "answer": "A"}]}'
    sdk = FakeSDK([response] * 4)
    client = OpenAICompatibleClient(settings(concurrency_limit=2), sdk=sdk)
    messages = [Message(role=MessageRole.USER, content="Source")]

    await asyncio.gather(*(client.generate(messages, QAResponse) for _ in range(4)))

    assert sdk.peak == 2


def test_llm_settings_validate_bounds_and_hide_key() -> None:
    config = settings(api_key="local-secret")
    assert "local-secret" not in repr(config)
    with pytest.raises(ValidationError):
        settings(concurrency_limit=0)
