import logging
from uuid import uuid4

import pytest

from dataset_builder.application.distillation import DistillationResponse, DistillationService
from dataset_builder.db.orm import ChunkRow, DistillationJobRow, TrainingSampleRow
from dataset_builder.models import Message


class FakeTeacherClient:
    def __init__(self, answers: list[str]) -> None:
        self.answers = iter(answers)
        self.requests: list[list[Message]] = []

    async def generate(
        self,
        messages: list[Message],
        response_model: type[DistillationResponse],
    ) -> DistillationResponse:
        self.requests.append(messages)
        return response_model(answer=next(self.answers))


class RecordingSession:
    def __init__(self, job: DistillationJobRow) -> None:
        self.job = job
        self.added: TrainingSampleRow | None = None
        self.flushed_before_reference = False

    def add(self, row: TrainingSampleRow) -> None:
        self.added = row

    async def flush(self, rows: list[TrainingSampleRow]) -> None:
        self.flushed_before_reference = rows == [self.added] and self.job.candidate_sample_id is None


def test_distillation_response_trims_and_rejects_blank_answer() -> None:
    response = DistillationResponse.model_validate({"answer": " 教师回答 "})

    assert response.answer == "教师回答"
    with pytest.raises(ValueError):
        DistillationResponse.model_validate({"answer": " "})


@pytest.mark.asyncio
async def test_distillation_hides_old_answers_across_turns(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="dataset_builder.application.distillation")
    source_id, run_id, job_id = uuid4(), uuid4(), uuid4()
    seed = TrainingSampleRow(
        id=source_id,
        project_id=uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        messages=[
            {"role": "system", "content": "规则"},
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "旧第一答"},
            {"role": "user", "content": "追问"},
            {"role": "assistant", "content": "旧第二答"},
        ],
        metadata_={"source_name": "guide.md"},
    )
    chunk = ChunkRow(id=seed.chunk_id, document_id=seed.document_id, index=0, content="可信来源")
    client = FakeTeacherClient(["新第一答", "新第二答"])
    service = DistillationService(None, client)  # type: ignore[arg-type]

    candidate = await service._candidate(seed, chunk, "独立作答", run_id, job_id)

    assert [message.content for message in candidate.messages] == ["规则", "第一问", "新第一答", "追问", "新第二答"]
    assert candidate.metadata["distillation_source_id"] == str(source_id)
    assert candidate.metadata["distillation_method"] == "independent_answer"
    assert len(client.requests) == 2
    assert all("旧第一答" not in message.content for request in client.requests for message in request)
    assert all("旧第二答" not in message.content for request in client.requests for message in request)
    assert any(message.content == "新第一答" for message in client.requests[1])
    assert caplog.messages.count(
        f"请求教师回答：运行编号 {run_id}，任务编号 {job_id}，原样本编号 {source_id}，第 1 轮"
    ) == 1
    assert caplog.messages.count(
        f"请求教师回答：运行编号 {run_id}，任务编号 {job_id}，原样本编号 {source_id}，第 2 轮"
    ) == 1


@pytest.mark.asyncio
async def test_distillation_rejects_invalid_message_order() -> None:
    seed = TrainingSampleRow(
        id=uuid4(),
        project_id=uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        messages=[{"role": "assistant", "content": "旧回答"}],
        metadata_={},
    )
    chunk = ChunkRow(id=seed.chunk_id, document_id=seed.document_id, index=0, content="可信来源")
    service = DistillationService(None, FakeTeacherClient([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="消息顺序无效"):
        await service._candidate(seed, chunk, "独立作答", uuid4(), uuid4())


def test_distillation_replaces_legacy_output_contract_in_saved_prompt() -> None:
    chunk = ChunkRow(id=uuid4(), document_id=uuid4(), index=0, content="可信来源")
    request = DistillationService._messages(
        [Message(role="user", content="问题")],
        chunk,
        '事实保真\n只返回一个 json 对象，格式为 {"assistant_messages": ["回答"]}。',
    )

    assert '"answer"' in request[0].content
    assert "assistant_messages" not in request[0].content


@pytest.mark.asyncio
async def test_distillation_flushes_candidate_before_setting_job_foreign_key() -> None:
    job = DistillationJobRow(run_id=uuid4(), source_sample_id=uuid4())
    candidate = TrainingSampleRow(
        id=uuid4(),
        project_id=uuid4(),
        document_id=uuid4(),
        chunk_id=uuid4(),
        messages=[],
        metadata_={},
    )
    session = RecordingSession(job)

    await DistillationService._attach_candidate(session, job, candidate)  # type: ignore[arg-type]

    assert session.flushed_before_reference is True
    assert job.candidate_sample_id == candidate.id
